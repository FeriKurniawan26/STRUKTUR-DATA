import sys
import json
import re
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QMessageBox, QComboBox, QLabel, QDateEdit, QHeaderView, QSpacerItem, QSizePolicy, QInputDialog
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor, QPalette
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib import cm
import numpy as np

# Nama file untuk menyimpan data transaksi dan konfigurasi target tabungan
DB_FILE = 'database.json'
CONFIG_FILE = 'config.json'

# Stack undo untuk menyimpan transaksi yang dapat dibatalkan
undo_stack = []

# Fungsi memuat data transaksi dari file JSON
def load_data():
    try:
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Jika file tidak ada atau corrupt, kembalikan list kosong
        return []

# Fungsi menyimpan data transaksi ke file JSON
def save_data(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=2)

# Fungsi memuat konfigurasi target tabungan dari file JSON
def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Jika file tidak ada, buat konfigurasi default
        conf = {'target_tabungan': 0}
        save_config(conf)
        return conf

# Fungsi menyimpan konfigurasi target tabungan ke file JSON
def save_config(conf):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(conf, f, indent=2)

# Kelas input khusus yang memformat angka menjadi format Rupiah, misalnya 1000000 -> 1.000.000
class RupiahLineEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.textChanged.connect(self.format_rupiah)
        self._processing = False

    def format_rupiah(self, text):
        if self._processing:
            return
        self._processing = True

        # Simpan posisi kursor agar tidak pindah secara aneh saat diformat ulang
        cursor_pos = self.cursorPosition()
        clean_text = re.sub(r'\D', '', text)  # Hanya ambil digit angka
        if clean_text == '':
            self.setText('')
            self._processing = False
            return

        # Memecah angka tiap 3 digit dari belakang, lalu gabungkan dengan titik
        parts = []
        while clean_text:
            parts.insert(0, clean_text[-3:])
            clean_text = clean_text[:-3]
        formatted = '.'.join(parts)

        self.setText(formatted)

        # Adjust posisi kursor sesuai perubahan panjang string
        new_cursor_pos = cursor_pos + (len(formatted) - len(text))
        new_cursor_pos = max(0, min(new_cursor_pos, len(formatted)))
        self.setCursorPosition(new_cursor_pos)

        self._processing = False

# Dialog input dengan gaya khusus untuk input target tabungan
class CustomInputDialog(QInputDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setStyleSheet("""
            QLineEdit {
                background-color: white;
                color: black;
                border: 1px solid #ccc;
                border-radius: 6px;
                padding: 4px;
            }
            QLabel {
                color: black;
            }
            QPushButton {
                background-color: #4caf50;
                color: white;
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #388E3C;
            }
        """)

# Kelas utama aplikasi keuangan MHS
class MHSApp(QWidget):
    BOROS_LIMIT_HARI = 7  # Durasi hari berturut-turut untuk peringatan boros
    BOROS_BATAS_HARIAN = 1000000  # Batas pengeluaran harian disebut boros

    # Daftar kategori pemasukan dan pengeluaran standar
    PEMASUKAN_CATEGORIES = [
        "Uang bulanan", "Beasiswa", "Freelance",
        "Jualan", "Bonus", "Investasi", "Lainnya"
    ]
    PENGELUARAN_CATEGORIES = [
        "Makan & Minum", "Kos / Sewa Tempat Tinggal", "Transportasi",
        "Kuota / Internet", "Alat Kuliah", "Uang Kuliah / SPP",
        "Hiburan", "Belanja Pribadi", "Cicilan / Hutang",
        "Tabungan / Investasi", "Lainnya"
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Catatan Keuangan Mahasiswa")
        self.setGeometry(100, 100, 900, 700)

        # Muat data dan konfigurasi saat aplikasi dijalankan
        self.transaksi_data = load_data()
        self.filtered_data = self.transaksi_data.copy()
        self.config = load_config()

        self.init_ui()

    def init_ui(self):
        # Atur style tampilan standar
        self.apply_style()

        main_layout = QVBoxLayout()

        # Form untuk input data transaksi
        form_layout = QFormLayout()

        # Pilih jenis transaksi: pemasukan atau pengeluaran
        self.jenis_input = QComboBox()
        self.jenis_input.addItems(["pemasukan", "pengeluaran"])
        self.jenis_input.currentTextChanged.connect(self.update_kategori_options)

        # Pilih kategori sesuai jenis transaksi
        self.kategori_input = QComboBox()
        self.update_kategori_options()  # Atur kategori default berdasarkan jenis default

        # Input nominal dengan format Rupiah otomatis
        self.nominal_input = RupiahLineEdit()
        self.nominal_input.setPlaceholderText("Masukkan nominal dalam angka (otomatis format rupiah)")

        # Input tanggal dengan kalender popup, default hari ini
        self.tanggal_input = QDateEdit()
        self.tanggal_input.setCalendarPopup(True)
        self.tanggal_input.setDate(QDate.currentDate())

        # Tambahkan elemen form ke form layout
        form_layout.addRow(QLabel("Jenis:"), self.jenis_input)
        form_layout.addRow(QLabel("Kategori:"), self.kategori_input)
        form_layout.addRow(QLabel("Nominal:"), self.nominal_input)
        form_layout.addRow(QLabel("Tanggal:"), self.tanggal_input)

        # Tombol-tombol aksi
        self.tambah_btn = self.create_styled_button("Tambah Transaksi")
        self.tambah_btn.clicked.connect(self.add_transaction)

        self.undo_btn = self.create_styled_button("Undo Transaksi Terakhir")
        self.undo_btn.clicked.connect(self.undo_transaction)

        self.hapus_btn = self.create_styled_button("Hapus Transaksi Terpilih")
        self.hapus_btn.clicked.connect(self.delete_selected_transaction)

        self.edit_btn = self.create_styled_button("Edit Transaksi Terpilih")
        self.edit_btn.clicked.connect(self.edit_selected_transaction)

        self.chart_btn = self.create_styled_button("Tampilkan Diagram Lingkaran")
        self.chart_btn.clicked.connect(self.show_pie_chart)

        btn_input_layout = QHBoxLayout()
        btn_input_layout.addWidget(self.tambah_btn)
        btn_input_layout.addWidget(self.edit_btn)
        btn_input_layout.addWidget(self.hapus_btn)
        btn_input_layout.addWidget(self.undo_btn)
        btn_input_layout.addWidget(self.chart_btn)

        # Filter data transaksi agar lebih mudah mencari
        filter_layout = QHBoxLayout()

        self.filter_jenis_combo = QComboBox()
        self.filter_jenis_combo.addItem("Semua")  # Pilihan semua jenis
        self.filter_jenis_combo.addItems(["pemasukan", "pengeluaran"])
        self.filter_jenis_combo.currentTextChanged.connect(self.update_filter_kategori_options)
        self.filter_jenis_combo.currentTextChanged.connect(self.apply_filters)

        self.filter_kategori_combo = QComboBox()
        self.update_filter_kategori_options()
        self.filter_kategori_combo.currentTextChanged.connect(self.apply_filters)

        # Filter tanggal
        self.filter_tanggal_mulai = QDateEdit()
        self.filter_tanggal_mulai.setCalendarPopup(True)
        self.filter_tanggal_mulai.setDate(QDate.currentDate().addMonths(-1))  # Default 1 bulan lalu
        self.filter_tanggal_mulai.dateChanged.connect(self.apply_filters)

        self.filter_tanggal_akhir = QDateEdit()
        self.filter_tanggal_akhir.setCalendarPopup(True)
        self.filter_tanggal_akhir.setDate(QDate.currentDate())
        self.filter_tanggal_akhir.dateChanged.connect(self.apply_filters)

        # Tambahkan widgets ke layout filter
        filter_layout.addWidget(QLabel("Filter Jenis:"))
        filter_layout.addWidget(self.filter_jenis_combo)
        filter_layout.addWidget(QLabel("Filter Kategori:"))
        filter_layout.addWidget(self.filter_kategori_combo)
        filter_layout.addWidget(QLabel("Dari tanggal:"))
        filter_layout.addWidget(self.filter_tanggal_mulai)
        filter_layout.addWidget(QLabel("Sampai tanggal:"))
        filter_layout.addWidget(self.filter_tanggal_akhir)

        self.filter_reset_btn = self.create_styled_button("Reset Filter")
        self.filter_reset_btn.clicked.connect(self.reset_filters)
        filter_layout.addWidget(self.filter_reset_btn)

        # Tabel menampilkan data transaksi lengkap
        self.tabel = QTableWidget()
        self.tabel.setColumnCount(4)
        self.tabel.setHorizontalHeaderLabels(["Jenis", "Kategori", "Nominal", "Tanggal"])
        self.tabel.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabel.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabel.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # Label informasi saldo dan target tabungan
        self.label_saldo = QLabel("Saldo: Rp 0")
        self.label_target = QLabel("Target Tabungan Bulanan: Rp {:,}".format(self.config.get('target_tabungan', 0)))
        self.label_sisa_target = QLabel("Sisa Untuk Target: Rp 0")

        # Tombol set target tabungan dengan gaya khusus
        target_btn = self.create_styled_button("Set Target Tabungan")
        target_btn.clicked.connect(self.set_target_tabungan)
        target_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: black;
                border-radius: 12px;
                padding: 8px 20px;
                font-size: 16px;
                font-weight: bold;
                border: 1px solid #ccc;
            }
            QPushButton:hover { background-color: #f0f0f0; }
            QPushButton:pressed { background-color: #e0e0e0; }
        """)

        saldo_layout = QHBoxLayout()
        saldo_layout.addWidget(self.label_saldo)
        saldo_layout.addWidget(self.label_target)
        saldo_layout.addWidget(self.label_sisa_target)
        saldo_layout.addWidget(target_btn)
        saldo_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        # Tambahkan semua layout ke layout utama
        main_layout.addLayout(form_layout)
        main_layout.addLayout(btn_input_layout)
        main_layout.addSpacing(20)
        main_layout.addLayout(filter_layout)
        main_layout.addWidget(self.tabel)
        main_layout.addLayout(saldo_layout)

        self.setLayout(main_layout)

        # Tampilkan data transaksi awal
        self.display_data(self.transaksi_data)

    # Membuat tombol dengan style konsisten
    def create_styled_button(self, text):
        button = QPushButton(text)
        button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border-radius: 12px;
                padding: 8px 20px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #388E3C; }
            QPushButton:pressed { background-color: #1B5E20; }
        """)
        return button

    # Memperbarui pilihan kategori sesuai jenis transaksi yang dipilih
    def update_kategori_options(self):
        jenis = self.jenis_input.currentText()
        if jenis == "pemasukan":
            categories = self.PEMASUKAN_CATEGORIES
        elif jenis == "pengeluaran":
            categories = self.PENGELUARAN_CATEGORIES
        else:
            categories = []
        current = self.kategori_input.currentText() if hasattr(self, 'kategori_input') else ''
        self.kategori_input.blockSignals(True)
        self.kategori_input.clear()
        self.kategori_input.addItems(categories)
        # Jika kategori sebelumnya masih ada, set sebagai pilihan saat ini
        if current in categories:
            index = self.kategori_input.findText(current)
            if index >= 0:
                self.kategori_input.setCurrentIndex(index)
        self.kategori_input.blockSignals(False)

    # Memperbarui pilihan kategori filter sesuai jenis filter yang dipilih
    def update_filter_kategori_options(self):
        jenis = self.filter_jenis_combo.currentText()
        if jenis == "pemasukan":
            categories = ["Semua"] + self.PEMASUKAN_CATEGORIES
        elif jenis == "pengeluaran":
            categories = ["Semua"] + self.PENGELUARAN_CATEGORIES
        else:
            categories = ["Semua"]
        current = self.filter_kategori_combo.currentText() if hasattr(self, 'filter_kategori_combo') else ''
        self.filter_kategori_combo.blockSignals(True)
        self.filter_kategori_combo.clear()
        self.filter_kategori_combo.addItems(categories)
        if current in categories:
            index = self.filter_kategori_combo.findText(current)
            if index >= 0:
                self.filter_kategori_combo.setCurrentIndex(index)
        self.filter_kategori_combo.blockSignals(False)

    # Menerapkan gaya umum aplikasi agar seragam dan mudah dibaca
    def apply_style(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 250))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
        self.setPalette(palette)
        self.setStyleSheet("""
            QLabel, QComboBox, QDateEdit {
                color: black;
                background-color: transparent;
            }
            QTableWidget {
                background-color: white;
                color: black;
                gridline-color: #ddd;
            }
            QTableWidget::item:selected {
                background-color: #4caf50;
                color: white;
            }
            QLineEdit {
                background-color: white;
                color: black;
                border: 1px solid #ccc;
                border-radius: 6px;
            }
            QComboBox {
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 6px;
            }
            QDateEdit {
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 6px;
            }
        """)

    # Membuka dialog untuk set target tabungan bulanan
    def set_target_tabungan(self):
        dialog = CustomInputDialog(self)
        dialog.setWindowTitle("Set Target Tabungan Bulanan")
        dialog.setLabelText("Masukkan target (angka):")
        dialog.setTextValue(str(self.config.get('target_tabungan', 0)))
        ok = dialog.exec()
        if ok:
            text = dialog.textValue()
            try:
                # Parsing input dengan menghapus titik ribuan
                target = int(text.replace('.', '').strip())
                if target < 0:
                    raise ValueError
                self.config['target_tabungan'] = target
                save_config(self.config)
                self.label_target.setText("Target Tabungan Bulanan: Rp {:,}".format(target))
                self.update_sisa_target()
            except ValueError:
                self.show_warning("Target harus berupa angka positif!")

    # Mengupdate label sisa target tabungan berdasarkan saldo terkini
    def update_sisa_target(self):
        saldo = self.calculate_saldo()
        target = self.config.get('target_tabungan', 0)
        sisa = target - saldo
        if sisa < 0:
            sisa = 0
        # Format angka untuk tampilan Rupiah
        self.label_sisa_target.setText(f"Sisa Untuk Target: Rp {sisa:,}".replace(',', '.'))

    # Menghitung saldo berdasarkan total pemasukan dikurangi pengeluaran
    def calculate_saldo(self):
        total_pemasukan = sum(t['nominal'] for t in self.transaksi_data if t['jenis'] == 'pemasukan')
        total_pengeluaran = sum(t['nominal'] for t in self.transaksi_data if t['jenis'] == 'pengeluaran')
        saldo = total_pemasukan - total_pengeluaran
        return saldo

    # Menampilkan data transaksi ke tabel termasuk total pemasukan dan pengeluaran
    def display_data(self, data):
        self.filtered_data = data
        count_data = len(data)
        # Buat baris untuk transaksi ditambah 2 baris tambahan untuk total
        self.tabel.setRowCount(count_data + 2)

        total_pemasukan = 0
        total_pengeluaran = 0
        for i, transaksi in enumerate(data):
            # Isi baris tabel dengan data transaksi
            self.tabel.setItem(i, 0, QTableWidgetItem(transaksi['jenis']))
            self.tabel.setItem(i, 1, QTableWidgetItem(transaksi['kategori']))
            self.tabel.setItem(i, 2, QTableWidgetItem(f"{transaksi['nominal']:,}".replace(',', '.')))
            self.tabel.setItem(i, 3, QTableWidgetItem(transaksi['tanggal']))
            if transaksi['jenis'] == 'pemasukan':
                total_pemasukan += transaksi['nominal']
            elif transaksi['jenis'] == 'pengeluaran':
                total_pengeluaran += transaksi['nominal']

        # Tambahkan baris total pemasukan dengan gaya khusus (non-editable, background khusus)
        pemasukan_item = QTableWidgetItem("Total Pemasukan")
        pemasukan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        pemasukan_item.setFlags(Qt.ItemFlag.NoItemFlags)
        total_pemasukan_item = QTableWidgetItem(f"Rp {total_pemasukan:,}".replace(',', '.'))
        total_pemasukan_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        total_pemasukan_item.setFlags(Qt.ItemFlag.NoItemFlags)

        kosong1 = QTableWidgetItem("")
        kosong1.setFlags(Qt.ItemFlag.NoItemFlags)
        kosong2 = QTableWidgetItem("")
        kosong2.setFlags(Qt.ItemFlag.NoItemFlags)

        row_pemasukan = count_data
        self.tabel.setItem(row_pemasukan, 0, pemasukan_item)
        self.tabel.setItem(row_pemasukan, 1, kosong1)
        self.tabel.setItem(row_pemasukan, 2, total_pemasukan_item)
        self.tabel.setItem(row_pemasukan, 3, kosong2)

        # Tambahkan baris total pengeluaran dengan gaya yang sama
        pengeluaran_item = QTableWidgetItem("Total Pengeluaran")
        pengeluaran_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        pengeluaran_item.setFlags(Qt.ItemFlag.NoItemFlags)
        total_pengeluaran_item = QTableWidgetItem(f"Rp {total_pengeluaran:,}".replace(',', '.'))
        total_pengeluaran_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        total_pengeluaran_item.setFlags(Qt.ItemFlag.NoItemFlags)

        kosong3 = QTableWidgetItem("")
        kosong3.setFlags(Qt.ItemFlag.NoItemFlags)
        kosong4 = QTableWidgetItem("")
        kosong4.setFlags(Qt.ItemFlag.NoItemFlags)

        row_pengeluaran = count_data + 1
        self.tabel.setItem(row_pengeluaran, 0, pengeluaran_item)
        self.tabel.setItem(row_pengeluaran, 1, kosong3)
        self.tabel.setItem(row_pengeluaran, 2, total_pengeluaran_item)
        self.tabel.setItem(row_pengeluaran, 3, kosong4)

        # Beri warna dan font bold untuk baris total pemasukan dan pengeluaran
        for r in (row_pemasukan, row_pengeluaran):
            for c in range(4):
                item = self.tabel.item(r, c)
                if item:
                    item.setBackground(QColor(230, 230, 250))  # Berwarna soft ungu
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)

        # Update tampilan saldo dan sisa target tabungan
        self.update_summary(total_pemasukan, total_pengeluaran)
        self.update_sisa_target()

    # Update label saldo saat ini berdasarkan total pemasukan dan pengeluaran
    def update_summary(self, total_pemasukan, total_pengeluaran):
        saldo = total_pemasukan - total_pengeluaran
        self.label_saldo.setText(f"Saldo: Rp {saldo:,}".replace(',', '.'))

    # Mengubah string nominal format rupiah menjadi integer
    def parse_int_nominal(self, nominal_text):
        try:
            clean_text = nominal_text.replace('.', '').strip()
            return int(clean_text)
        except:
            return None

    # Menambah transaksi baru berdasarkan input form
    def add_transaction(self):
        jenis = self.jenis_input.currentText()
        kategori = self.kategori_input.currentText().strip()
        nominal_text = self.nominal_input.text()
        tanggal_qdate = self.tanggal_input.date()
        tanggal = tanggal_qdate.toString("yyyy-MM-dd")

        # Validasi input kategori tidak kosong
        if not kategori:
            self.show_warning("Kategori tidak boleh kosong!")
            return

        # Parsing nominal ke integer dan validasi positif
        nominal = self.parse_int_nominal(nominal_text)
        if nominal is None or nominal <= 0:
            self.show_warning("Nominal harus berupa angka positif!")
            return

        transaksi = {"jenis": jenis, "kategori": kategori, "nominal": nominal, "tanggal": tanggal}
        self.transaksi_data.append(transaksi)  # Tambah ke data utama
        undo_stack.append(transaksi)  # Tambah ke stack undo
        save_data(self.transaksi_data)  # Simpan ke file

        # Perbarui opsi kategori dan filter, reset input, terapkan filter ke tabel
        self.update_kategori_options()
        self.update_filter_kategori_options()
        self.reset_inputs()
        self.apply_filters()

        # Cek peringatan boros dan saldo negatif setelah tambah transaksi
        self.check_boros_warning()
        self.check_saldo_negatif()

        self.update_sisa_target()
        self.show_info("Transaksi berhasil ditambahkan.")

    # Reset field input setelah transaksi berhasil ditambahkan
    def reset_inputs(self):
        self.nominal_input.clear()
        self.jenis_input.setCurrentIndex(0)
        self.update_kategori_options()
        if self.kategori_input.count() > 0:
            self.kategori_input.setCurrentIndex(0)
        self.tanggal_input.setDate(QDate.currentDate())

    # Undo transaksi terakhir yang ditambahkan
    def undo_transaction(self):
        if undo_stack:
            last = undo_stack.pop()
            try:
                self.transaksi_data.remove(last)
                save_data(self.transaksi_data)
                self.apply_filters()
                self.check_saldo_negatif()
                self.update_sisa_target()
                self.show_info("Transaksi terakhir berhasil di-undo.")
            except ValueError:
                self.show_warning("Transaksi terakhir tidak ditemukan.")
        else:
            self.show_info("Tidak ada transaksi yang bisa di-undo.")

    # Mendapatkan index transaksi yang dipilih di tabel, disesuaikan dengan data yang difilter
    def get_selected_transaction_index(self):
        selected_items = self.tabel.selectedItems()
        if not selected_items:
            return None
        selected_row = selected_items[0].row()
        if selected_row >= len(self.filtered_data):
            return None
        transaksi = self.filtered_data[selected_row]
        try:
            return self.transaksi_data.index(transaksi)  # Dapatkan index asli di data utama
        except ValueError:
            return None

    # Menghapus transaksi yang dipilih
    def delete_selected_transaction(self):
        idx = self.get_selected_transaction_index()
        if idx is None:
            self.show_warning("Tidak ada transaksi yang dipilih.")
            return

        reply = QMessageBox.question(self, 'Konfirmasi',
                                     "Apakah Anda yakin ingin menghapus transaksi ini?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            transaksi = self.transaksi_data.pop(idx)
            if transaksi in undo_stack:
                undo_stack.remove(transaksi)
            save_data(self.transaksi_data)
            self.update_kategori_options()
            self.update_filter_kategori_options()
            self.apply_filters()
            self.check_saldo_negatif()
            self.update_sisa_target()
            self.show_info("Transaksi berhasil dihapus.")

    # Mengedit transaksi yang dipilih melalui serangkaian dialog input
    def edit_selected_transaction(self):
        idx = self.get_selected_transaction_index()
        if idx is None:
            self.show_warning("Tidak ada transaksi yang dipilih.")
            return

        transaksi = self.transaksi_data[idx]

        # Dialog edit jenis transaksi
        jenis_baru, ok1 = QInputDialog.getItem(
            self,
            "Edit Jenis",
            "Jenis (pemasukan/pengeluaran):",
            ["pemasukan", "pengeluaran"],
            current=0 if transaksi['jenis'] == 'pemasukan' else 1,
            editable=False)
        if not ok1:
            return
        
        # Sesuaikan kategori berdasarkan jenis baru
        if jenis_baru == "pemasukan":
            categories = self.PEMASUKAN_CATEGORIES
        else:
            categories = self.PENGELUARAN_CATEGORIES

        kategori_lama = transaksi['kategori'] if transaksi['kategori'] in categories else categories[0]
        kategori_baru, ok2 = QInputDialog.getItem(self, "Edit Kategori", "Kategori:", categories, current=categories.index(kategori_lama), editable=False)
        if not ok2 or not kategori_baru.strip():
            self.show_warning("Kategori tidak boleh kosong!")
            return

        # Edit nominal transaksi dalam format rupiah
        nominal_lama_str = f"{transaksi['nominal']:,}".replace(',', '.')
        nominal_baru_str, ok3 = QInputDialog.getText(self, "Edit Nominal", "Nominal:", text=nominal_lama_str)
        if not ok3:
            return
        nominal_baru = self.parse_int_nominal(nominal_baru_str)
        if nominal_baru is None or nominal_baru <= 0:
            self.show_warning("Nominal harus berupa angka positif!")
            return

        # Edit tanggal transaksi
        tanggal_lama = transaksi['tanggal']
        tanggal_baru_str, ok4 = QInputDialog.getText(self, "Edit Tanggal", "Tanggal (YYYY-MM-DD):", text=tanggal_lama)
        if not ok4:
            return
        try:
            datetime.strptime(tanggal_baru_str, "%Y-%m-%d")
        except ValueError:
            self.show_warning("Format tanggal salah! Gunakan YYYY-MM-DD")
            return

        # Update data transaksi
        transaksi_updated = {
            "jenis": jenis_baru,
            "kategori": kategori_baru.strip(),
            "nominal": nominal_baru,
            "tanggal": tanggal_baru_str
        }
        self.transaksi_data[idx] = transaksi_updated
        save_data(self.transaksi_data)
        self.update_kategori_options()
        self.update_filter_kategori_options()
        self.apply_filters()
        self.check_saldo_negatif()
        self.update_sisa_target()
        self.show_info("Transaksi berhasil diupdate.")

    # Terapkan filter data dan tampilkan sesuai filter
    def apply_filters(self):
        jenis_filter = self.filter_jenis_combo.currentText()
        kategori_filter = self.filter_kategori_combo.currentText()
        tanggal_mulai = self.filter_tanggal_mulai.date().toString("yyyy-MM-dd")
        tanggal_akhir = self.filter_tanggal_akhir.date().toString("yyyy-MM-dd")

        filtered = []
        for t in self.transaksi_data:
            # Filter jenis
            if jenis_filter != "Semua" and t['jenis'] != jenis_filter:
                continue
            # Filter kategori, abaikan case dan filter hanya jika bukan 'Semua'
            if kategori_filter != "Semua" and t['kategori'].lower() != kategori_filter.lower():
                continue
            # Filter tanggal rentang mulai-akhir
            if t['tanggal'] < tanggal_mulai or t['tanggal'] > tanggal_akhir:
                continue
            filtered.append(t)
        self.display_data(filtered)

    # Reset seluruh filter ke default dan tampilkan seluruh data
    def reset_filters(self):
        self.filter_jenis_combo.setCurrentIndex(0)
        self.update_filter_kategori_options()
        self.filter_kategori_combo.setCurrentIndex(0)
        self.filter_tanggal_mulai.setDate(QDate.currentDate().addMonths(-1))
        self.filter_tanggal_akhir.setDate(QDate.currentDate())
        self.apply_filters()

    # Cek apakah pengeluaran boros terjadi lebih dari batas hari berturut-turut
    def check_boros_warning(self):
        hari_ini = datetime.now().date()
        consecutive_boros = 0

        # Loop mundur dari hari ini mengecek total pengeluaran tiap hari
        for hari_offset in range(self.BOROS_LIMIT_HARI):
            cek_tanggal = hari_ini - timedelta(days=hari_offset)
            cek_tanggal_str = cek_tanggal.strftime("%Y-%m-%d")
            total_harian = sum(
                t['nominal']
                for t in self.transaksi_data
                if t['jenis'] == 'pengeluaran' and t['tanggal'] == cek_tanggal_str
            )
            if total_harian > self.BOROS_BATAS_HARIAN:
                consecutive_boros += 1
            else:
                break  # Jika hari tidak boros, reset hitungan

        # Jika selama BOROS_LIMIT_HARI berturut-turut boros, tampilkan peringatan
        if consecutive_boros >= self.BOROS_LIMIT_HARI:
            msg = QMessageBox(self)
            msg.setWindowTitle("Peringatan Pengeluaran Boros")
            msg.setText(f"Anda telah menghabiskan pengeluaran boros selama {self.BOROS_LIMIT_HARI} hari berturut-turut.\nMari mulai hemat dan kelola keuangan Anda dengan bijak!")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: white;
                    color: black;
                }
                QPushButton {
                    background-color: #4caf50;
                    color: white;
                    border-radius: 10px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #388E3C; }
            """)
            msg.exec()

    # Cek apakah saldo negatif dan tampilkan peringatan jika iya
    def check_saldo_negatif(self):
        saldo = self.calculate_saldo()
        if saldo < 0:
            msg = QMessageBox(self)
            msg.setWindowTitle("Peringatan Saldo Negatif")
            msg.setText(f"Saldo Anda saat ini adalah Rp {saldo:,} (negatif).\nMohon atur pengeluaran Anda dengan bijak agar tidak boros dan terhindar dari saldo minus.")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: white;
                    color: black;
                }
                QPushButton {
                    background-color: #4caf50;
                    color: white;
                    border-radius: 10px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #388E3C; }
            """)
            msg.exec()

    # Fungsi menampilkan pesan informasi
    def show_info(self, message):
        msg = QMessageBox(self)
        msg.setWindowTitle("Informasi")
        msg.setText(message)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: white;
                color: black;
            }
            QPushButton {
                background-color: #4caf50;
                color: white;
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #388E3C; }
        """)
        msg.exec()

    # Fungsi menampilkan peringatan
    def show_warning(self, message):
        msg = QMessageBox(self)
        msg.setWindowTitle("Peringatan")
        msg.setText(message)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: white;
                color: black;
            }
            QPushButton {
                background-color: #4caf50;
                color: white;
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #388E3C; }
        """)
        msg.exec()

    # Menampilkan diagram lingkaran dari data pemasukan dan pengeluaran
    def show_pie_chart(self):
        pemasukan_categories = {}
        pengeluaran_categories = {}

        # Gunakan data yang difilter jika ada, jika tidak gunakan semua data
        data_for_chart = self.filtered_data if self.filtered_data else self.transaksi_data

        for t in data_for_chart:
            cat = t['kategori']
            if t['jenis'] == 'pemasukan':
                pemasukan_categories[cat] = pemasukan_categories.get(cat, 0) + t['nominal']
            elif t['jenis'] == 'pengeluaran':
                pengeluaran_categories[cat] = pengeluaran_categories.get(cat, 0) + t['nominal']

        # Fungsi untuk men-styling grafik pie
        def style_pie(ax, sizes, labels, title, positive):
            if not sizes:
                ax.text(0.5,0.5, f"Tidak ada data\n{title.lower()}", ha='center', va='center', fontsize=14, color='gray')
                ax.set_title(title, fontsize=16, weight='bold', pad=15)
                ax.axis('off')
                return None, None

            total = sum(sizes)
            sorted_pairs = sorted(zip(sizes, labels), reverse=True)
            sizes_s, labels_s = zip(*sorted_pairs)

            explode = [0.05] + [0.01]*(len(sizes_s)-1)
            cmap = cm.Greens if positive else cm.Reds
            colors = cmap(np.linspace(0.5, 0.85, len(sizes_s)))

            wedges, texts, autotexts = ax.pie(
                sizes_s, explode=explode, labels=labels_s, autopct=lambda pct: f"{pct:.1f}%\n(Rp {int(pct*total/100):,})".replace(',', '.'),
                shadow=True, startangle=140, colors=colors, wedgeprops=dict(width=0.4, edgecolor='w')
            )
            plt.setp(autotexts, size=10, weight="bold", color="white")
            plt.setp(texts, size=11, weight="semibold")

            ax.set_title(title, fontsize=18, weight='bold', pad=15)

            legend_labels = [f"{lbl}: Rp {val:,}".replace(',', '.') for lbl, val in zip(labels_s, sizes_s)]
            if ax.legend_:
                ax.legend_.remove()
            return wedges, legend_labels

        pemasukan_labels = list(pemasukan_categories.keys())
        pemasukan_sizes = list(pemasukan_categories.values())
        pengeluaran_labels = list(pengeluaran_categories.keys())
        pengeluaran_sizes = list(pengeluaran_categories.values())

        # Jika tidak ada data sama sekali, tampilkan info
        if not pemasukan_sizes and not pengeluaran_sizes:
            self.show_info("Tidak ada data pemasukan atau pengeluaran untuk ditampilkan.")
            return

        # Plot dua pie chart berdampingan, pemasukan (hijau) dan pengeluaran (merah)
        fig, axs = plt.subplots(1, 2, figsize=(14,7), subplot_kw=dict(aspect="equal"))

        wedges_in, labels_in = style_pie(axs[0], pemasukan_sizes, pemasukan_labels, "Pemasukan", True)
        wedges_out, labels_out = style_pie(axs[1], pengeluaran_sizes, pengeluaran_labels, "Pengeluaran", False)

        patches = []
        patches_labels = []
        if wedges_in:
            patches.extend(wedges_in)
            patches_labels.extend(labels_in)
        if wedges_out:
            patches.extend(wedges_out)
            patches_labels.extend(labels_out)

        if patches:
            fig.legend(patches, patches_labels, loc='center right', fontsize=11, title="Kategori Detail", title_fontsize=13)

        plt.subplots_adjust(right=0.8)
        fig.suptitle("Diagram Lingkaran Pemasukan dan Pengeluaran Per Kategori", fontsize=22, weight='bold', y=1.02)
        plt.tight_layout()

        plt.show()

# Inisialisasi dan jalankan aplikasi PyQt6
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MHSApp()
    window.show()
    sys.exit(app.exec())
