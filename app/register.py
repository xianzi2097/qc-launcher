"""
QC Launcher — 批量注册模块
三栏层次结构：老师 → 班级 → 学生
支持机构一次性批量初始化。
"""

import os
import sys
import json
import random
from collections import OrderedDict

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QLineEdit, QGroupBox, QMessageBox,
    QProgressBar, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, QThread, Signal, QEvent
from PySide6.QtGui import QFont

# ---------------------------------------------------------------------------
#  按钮 / 控件样式
# ---------------------------------------------------------------------------
BTN_PRIMARY = """
    QPushButton {{ border: none; border-radius: 5px; padding: 6px 24px;
        background: {bg}; color: white; font-weight: bold; }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:disabled {{ background: #94a3b8; }}
"""
BTN_SECONDARY = """
    QPushButton {{ border: none; border-radius: 5px; padding: 5px 14px;
        background: #e2e8f0; color: #475569; font-weight: bold; }}
    QPushButton:hover {{ background: #cbd5e1; }}
"""
INPUT_STYLE = """
    QLineEdit { border: 1px solid #e2e8f0; border-radius: 4px;
        padding: 4px 8px; background: white; }
    QLineEdit:focus { border-color: #3b82f6; }
"""
LIST_STYLE = """
    QListWidget { border: 1px solid #e2e8f0; border-radius: 6px;
        background: white; outline: none; }
    QListWidget::item { padding: 6px 8px; border-radius: 4px; }
    QListWidget::item:selected { background: #dbeafe; color: #1e293b; }
    QListWidget::item:hover { background: #f1f5f9; }
"""


# ============================================================
#  注册工作线程
# ============================================================

class RegisterWorker(QThread):
    progress = Signal(str)
    done_signal = Signal(int, int)   # (success, fail)
    progress_pct = Signal(int)

    def __init__(self, backend_dir: str, data_dir: str,
                 data: OrderedDict, default_password: str, mode: str = "register"):
        super().__init__()
        self.backend_dir = backend_dir
        self.data_dir = data_dir
        self.data = data
        self.default_password = default_password
        self.mode = mode

    def run(self):
        if self.backend_dir not in sys.path:
            sys.path.insert(0, self.backend_dir)
        try:
            from models import SessionLocal, UserModel
            from utils import ensure_user_dirs, _save_classes, _load_classes
        except ImportError as e:
            self.progress.emit(f"❌ 无法导入后端模块: {e}")
            self.done_signal.emit(0, 0)
            return

        db = SessionLocal()
        total_students = sum(len(s) for t in self.data.values() for s in t["classes"].values())
        total = len(self.data) + total_students
        done = 0
        success = 0
        fail = 0
        created_tids = {}

        def _pct():
            self.progress_pct.emit(int(done / max(total, 1) * 100))

        # ── 1. 注册老师 ──
        for tname in self.data:
            existing = db.query(UserModel).filter(UserModel.username == tname).first()
            if existing:
                if existing.role != "teacher":
                    self.progress.emit(f"⏭️  [{tname}] 已是 {existing.role}，跳过")
                else:
                    self.progress.emit(f"⏭️  [{tname}] 已存在，复用")
                    created_tids[tname] = existing.id
                done += 1; _pct(); continue
            try:
                avatar = f"avatar_{str(random.randint(1,78)).zfill(2)}.jpg"
                user = UserModel(username=tname, password=self.default_password,
                                 role="teacher", avatar_path=avatar, qc_descriptors="{}")
                db.add(user); db.commit(); db.refresh(user)
                ensure_user_dirs(user)
                created_tids[tname] = user.id
                self.progress.emit(f"✅ 老师 [{tname}]")
                done += 1; success += 1; _pct()
            except Exception as e:
                db.rollback()
                self.progress.emit(f"❌ 老师 [{tname}]: {e}")
                done += 1; fail += 1; _pct()

        # ── 2. 学生 + classes.json ──
        for tname, tdata in self.data.items():
            tid = created_tids.get(tname)
            if tid is None: continue
            if self.mode == "manage":
                classes = []  # 完全替换
            else:
                classes = _load_classes(tname)
            for cname, snames in tdata["classes"].items():
                existing_c = next((c for c in classes if c["name"] == cname), None)
                if existing_c is None:
                    existing_c = {"name": cname, "schedule": [], "students": []}
                    classes.append(existing_c)
                if self.mode == "manage":
                    existing_c["students"] = []
                for sname in snames:
                    sname = sname.strip()
                    if not sname: continue
                    existing = db.query(UserModel).filter(UserModel.username == sname).first()
                    if existing:
                        if existing.role != "student":
                            self.progress.emit(f"⏭️  [{sname}] 已是 {existing.role}")
                            done += 1; _pct(); continue
                        uid = existing.id
                        self.progress.emit(f"⏭️  [{sname}] 已存在，加入班级")
                    else:
                        try:
                            avatar = f"avatar_{str(random.randint(1,78)).zfill(2)}.jpg"
                            user = UserModel(username=sname, password=self.default_password,
                                             role="student", avatar_path=avatar,
                                             qc_descriptors=json.dumps({"teacher": tname}, ensure_ascii=False))
                            db.add(user); db.commit(); db.refresh(user)
                            ensure_user_dirs(user)
                            uid = user.id
                            self.progress.emit(f"✅ 学生 [{sname}]")
                            success += 1
                        except Exception as e:
                            db.rollback()
                            self.progress.emit(f"❌ 学生 [{sname}]: {e}")
                            fail += 1; done += 1; _pct(); continue
                    if not any(s.get("user_id") == uid for s in existing_c["students"]):
                        existing_c["students"].append({"user_id": uid, "name": sname})
                        self.progress.emit(f"   → 加入 [{cname}]")
                    done += 1; _pct()
            _save_classes(tname, classes)

        db.close()
        self.done_signal.emit(success, fail)


# ============================================================
#  批量注册对话框
# ============================================================

class BatchRegisterDialog(QDialog):

    def __init__(self, backend_dir: str, data_dir: str, parent=None, mode: str = "register"):
        super().__init__(parent)
        self.backend_dir = backend_dir
        self.data_dir = data_dir
        self.mode = mode
        self._worker = None
        self._data = OrderedDict()
        self._selected_teacher = None
        self._selected_class = None

        self.setWindowTitle("账号管理" if mode == "manage" else "账号注册")
        self.setMinimumSize(850, 520)
        self.resize(900, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build_ui()
        if mode == "manage":
            self._load_existing()

    # ── 数据辅助 ──

    def _ensure_teacher(self, name: str):
        if name not in self._data:
            self._data[name] = {"classes": OrderedDict()}

    def _ensure_class(self, teacher: str, class_name: str):
        self._ensure_teacher(teacher)
        if class_name not in self._data[teacher]["classes"]:
            self._data[teacher]["classes"][class_name] = []

    def _load_existing(self):
        """扫描 DB + 文件系统，加载现有老师/班级/学生"""
        if self.backend_dir not in sys.path:
            sys.path.insert(0, self.backend_dir)
        try:
            from models import SessionLocal, UserModel
        except ImportError:
            return

        db = SessionLocal()
        try:
            teachers = db.query(UserModel).filter(UserModel.role == "teacher").all()
            for t in teachers:
                self._ensure_teacher(t.username)
                try:
                    from utils import _load_classes
                    classes = _load_classes(t.username)
                    for c in classes:
                        cname = c.get("name", "")
                        if not cname:
                            continue
                        self._ensure_class(t.username, cname)
                        for s in c.get("students", []):
                            sname = s.get("name", s.get("username", ""))
                            if sname and sname not in self._data[t.username]["classes"][cname]:
                                self._data[t.username]["classes"][cname].append(sname)
                except Exception:
                    pass
        finally:
            db.close()

        self._refresh_teachers()
        self._update_preview()

    # ── UI ──

    def _build_ui(self):
        layout = QVBoxLayout(self); layout.setSpacing(8)

        # 密码 + 预览（管理模式隐藏密码）
        if self.mode == "register":
            pwd_row = QHBoxLayout()
            pwd_row.addWidget(QLabel("默认密码：", font=QFont("Microsoft YaHei", 9)))
            self.pwd_input = QLineEdit("111111")
            self.pwd_input.setFont(QFont("Consolas", 10))
            self.pwd_input.setStyleSheet(INPUT_STYLE); self.pwd_input.setFixedWidth(160)
            pwd_row.addWidget(self.pwd_input)
            self.preview_label = QLabel("")
            self.preview_label.setFont(QFont("Microsoft YaHei", 9))
            self.preview_label.setStyleSheet("color: #64748b; margin-left: 12px;")
            pwd_row.addWidget(self.preview_label)
            pwd_row.addStretch()
            layout.addLayout(pwd_row)
        else:
            self.pwd_input = None
            self.preview_label = QLabel("")
            self.preview_label.setFont(QFont("Microsoft YaHei", 9))
            self.preview_label.setStyleSheet("color: #64748b;")
            layout.addWidget(self.preview_label)

        # 三栏
        cols = QHBoxLayout(); cols.setSpacing(10)
        cols.addWidget(self._build_teacher_col(), 1)
        cols.addWidget(self._build_class_col(), 1)
        cols.addWidget(self._build_student_col(), 1)
        layout.addLayout(cols, 1)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False); self.progress_bar.setMaximumHeight(18)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border:1px solid #e2e8f0; border-radius:4px; text-align:center; }
            QProgressBar::chunk { background:#22c55e; border-radius:3px; }
        """)
        layout.addWidget(self.progress_bar)

        # 日志
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True); self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setMaximumHeight(120); self.log_area.setVisible(False)
        self.log_area.setStyleSheet("""
            QTextEdit { border:1px solid #e2e8f0; border-radius:6px;
                background:#0f172a; color:#e2e8f0; padding:6px; }
        """)
        layout.addWidget(self.log_area)

        # 按钮
        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel_btn = QPushButton("关闭")
        cancel_btn.setFont(QFont("Microsoft YaHei", 9)); cancel_btn.setStyleSheet(BTN_SECONDARY)
        cancel_btn.setAutoDefault(False); cancel_btn.setDefault(False)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        if self.mode == "manage":
            label, color, hover = "保存更改", "#f59e0b", "#d97706"
        else:
            label, color, hover = "开始注册", "#22c55e", "#16a34a"
        self.register_btn = QPushButton(label)
        self.register_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.register_btn.setStyleSheet(BTN_PRIMARY.format(bg=color, hover=hover))
        self.register_btn.setAutoDefault(False); self.register_btn.setDefault(False)
        self.register_btn.clicked.connect(self._do_register)
        btn_row.addWidget(self.register_btn)
        layout.addLayout(btn_row)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Return:
            if obj is self.teacher_input:
                self._add_teacher()
                return True
            elif obj is self.class_input:
                self._add_class()
                return True
            elif obj is self.student_input:
                self._add_student()
                return True
        return super().eventFilter(obj, event)

    def _make_col(self, title: str, list_widget: QListWidget, input_widget: QLineEdit,
                  add_action, del_action, placeholder: str, enabled: bool):
        g = QGroupBox(title)
        g.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        v = QVBoxLayout(g); v.setSpacing(4)
        v.addWidget(list_widget)
        row = QHBoxLayout()
        input_widget.setPlaceholderText(placeholder)
        input_widget.setFont(QFont("Microsoft YaHei", 9))
        input_widget.setStyleSheet(INPUT_STYLE)
        input_widget.setEnabled(enabled)
        input_widget.installEventFilter(self)
        row.addWidget(input_widget)
        add_btn = QPushButton("＋")
        add_btn.setFixedSize(26, 26)
        add_btn.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        add_btn.setStyleSheet("QPushButton { border: none; border-radius: 4px; background: transparent; color: #22c55e; } QPushButton:hover { background: #dcfce7; }")
        add_btn.clicked.connect(add_action)
        row.addWidget(add_btn)
        if self.mode == "manage":
            del_btn = QPushButton("✕")
            del_btn.setFixedSize(26, 26)
            del_btn.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
            del_btn.setStyleSheet("QPushButton { border: none; border-radius: 4px; background: transparent; color: #ef4444; } QPushButton:hover { background: #fee2e2; }")
            del_btn.clicked.connect(del_action)
            row.addWidget(del_btn)
        v.addLayout(row)
        return g

    def _build_teacher_col(self):
        self.teacher_list = QListWidget()
        self.teacher_list.setStyleSheet(LIST_STYLE)
        self.teacher_list.setFont(QFont("Microsoft YaHei", 10))
        self.teacher_list.clicked.connect(self._on_teacher_clicked)
        self.teacher_input = QLineEdit()
        return self._make_col("👨‍🏫 老师", self.teacher_list, self.teacher_input,
                              self._add_teacher, self._del_teacher,
                              "输入老师名，回车或＋添加", True)

    def _build_class_col(self):
        self.class_list = QListWidget()
        self.class_list.setStyleSheet(LIST_STYLE)
        self.class_list.setFont(QFont("Microsoft YaHei", 10))
        self.class_list.clicked.connect(self._on_class_clicked)
        self.class_input = QLineEdit()
        return self._make_col("🏫 班级", self.class_list, self.class_input,
                              self._add_class, self._del_class,
                              "先选老师，再输班级名回车或＋", False)

    def _build_student_col(self):
        self.student_list = QListWidget()
        self.student_list.setStyleSheet(LIST_STYLE)
        self.student_list.setFont(QFont("Microsoft YaHei", 10))
        self.student_input = QLineEdit()
        return self._make_col("🧑‍🎓 学生", self.student_list, self.student_input,
                              self._add_student, self._del_student,
                              "先选班级，再输学生名回车或＋", False)

    # ── 事件 ──

    def _flash_status(self, msg: str):
        """临时在预览区显示错误信息，2 秒后恢复"""
        self.preview_label.setText(msg)
        self.preview_label.setStyleSheet("color: #ef4444; margin-left: 12px; font-weight: bold;")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, self._update_preview)

    def _add_teacher(self):
        name = self.teacher_input.text().strip()
        if not name: return
        if name in self._data:
            self._flash_status(f"❌ 老师「{name}」已存在")
            self.teacher_input.selectAll(); return
        self._ensure_teacher(name); self.teacher_input.clear()
        item = QListWidgetItem(f"{name}  (0班 0人)")
        item.setData(Qt.ItemDataRole.UserRole, name)
        self.teacher_list.addItem(item)
        self.teacher_list.setCurrentItem(item)
        self.teacher_list.scrollToItem(item)
        self._on_teacher_clicked()
        self._update_preview()
        self.teacher_input.setFocus()

    def _del_teacher(self):
        if self.mode != "manage": return
        item = self.teacher_list.currentItem()
        if not item: return
        name = item.data(Qt.ItemDataRole.UserRole)
        if self._selected_teacher == name:
            self._selected_teacher = None; self._selected_class = None
            self.class_list.clear(); self.student_list.clear()
            self.class_input.setEnabled(False); self.student_input.setEnabled(False)
        self._data.pop(name, None)
        self._refresh_teachers(); self._update_preview()

    def _add_class(self):
        if not self._selected_teacher: return
        name = self.class_input.text().strip()
        if not name: return
        tdata = self._data.get(self._selected_teacher)
        if tdata and name in tdata["classes"]:
            self._flash_status(f"❌ 班级「{name}」在 {self._selected_teacher} 下已存在")
            self.class_input.selectAll(); return
        self._ensure_class(self._selected_teacher, name); self.class_input.clear()
        item = QListWidgetItem(f"{name}  (0人)")
        item.setData(Qt.ItemDataRole.UserRole, name)
        self.class_list.addItem(item)
        self.class_list.setCurrentItem(item)
        self.class_list.scrollToItem(item)
        self._on_class_clicked()
        self._update_teacher_counts()
        self._update_preview()
        self.class_input.setFocus()

    def _del_class(self):
        if self.mode != "manage": return
        if not self._selected_teacher: return
        item = self.class_list.currentItem()
        if not item: return
        name = item.data(Qt.ItemDataRole.UserRole)
        if self._selected_class == name:
            self._selected_class = None
            self.student_list.clear(); self.student_input.setEnabled(False)
        if self._selected_teacher in self._data:
            self._data[self._selected_teacher]["classes"].pop(name, None)
        self._refresh_classes(); self._update_teacher_counts(); self._update_preview()

    def _add_student(self):
        if not self._selected_teacher or not self._selected_class: return
        name = self.student_input.text().strip()
        if not name: return
        self._ensure_class(self._selected_teacher, self._selected_class)
        lst = self._data[self._selected_teacher]["classes"][self._selected_class]
        if name in lst:
            self._flash_status(f"❌ 学生「{name}」在 {self._selected_class} 中已存在")
            self.student_input.selectAll(); return
        lst.append(name)
        self.student_input.clear()
        self.student_list.addItem(name)
        last = self.student_list.item(self.student_list.count() - 1)
        self.student_list.scrollToItem(last)
        self._update_class_counts()
        self._update_teacher_counts()
        self._update_preview()
        self.student_input.setFocus()

    def _del_student(self):
        if self.mode != "manage": return
        if not self._selected_teacher or not self._selected_class: return
        item = self.student_list.currentItem()
        if not item: return
        name = item.text()
        t, c = self._selected_teacher, self._selected_class
        if t in self._data and c in self._data[t]["classes"]:
            lst = self._data[t]["classes"][c]
            if name in lst: lst.remove(name)
        self._refresh_students(); self._update_class_counts(); self._update_teacher_counts(); self._update_preview()

    def _on_teacher_clicked(self):
        item = self.teacher_list.currentItem()
        if item:
            self._selected_teacher = item.data(Qt.ItemDataRole.UserRole)
            self._selected_class = None
            self.student_list.clear(); self.student_input.setEnabled(False)
            self.class_input.setEnabled(True)
            self.class_input.setPlaceholderText("输入班级名，回车添加")
        else:
            self._selected_teacher = None; self.class_input.setEnabled(False)
        self._refresh_classes(); self._update_preview()

    def _on_class_clicked(self):
        item = self.class_list.currentItem()
        if item:
            self._selected_class = item.data(Qt.ItemDataRole.UserRole)
            self.student_input.setEnabled(True)
            self.student_input.setPlaceholderText("输入学生名，回车添加")
        else:
            self._selected_class = None; self.student_input.setEnabled(False)
        self._refresh_students(); self._update_preview()

    # ── 局部刷新计数 ──

    def _update_teacher_counts(self):
        """只更新 teacher_list 中各项的计数显示，不重建"""
        for i in range(self.teacher_list.count()):
            item = self.teacher_list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            if name in self._data:
                cc = len(self._data[name]["classes"])
                sc = sum(len(s) for s in self._data[name]["classes"].values())
                item.setText(f"{name}  ({cc}班 {sc}人)")

    def _update_class_counts(self):
        """只更新 class_list 中各项的计数显示"""
        for i in range(self.class_list.count()):
            item = self.class_list.item(i)
            cname = item.data(Qt.ItemDataRole.UserRole)
            t = self._selected_teacher
            if t and t in self._data and cname in self._data[t]["classes"]:
                sc = len(self._data[t]["classes"][cname])
                item.setText(f"{cname}  ({sc}人)")

    # ── 刷新列表 ──

    def _refresh_teachers(self):
        self.teacher_list.clear()
        for name in self._data:
            cc = len(self._data[name]["classes"])
            sc = sum(len(s) for s in self._data[name]["classes"].values())
            item = QListWidgetItem(f"{name}  ({cc}班 {sc}人)")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.teacher_list.addItem(item)

    def _refresh_classes(self):
        self.class_list.clear()
        if not self._selected_teacher or self._selected_teacher not in self._data: return
        for cname, students in self._data[self._selected_teacher]["classes"].items():
            item = QListWidgetItem(f"{cname}  ({len(students)}人)")
            item.setData(Qt.ItemDataRole.UserRole, cname)
            self.class_list.addItem(item)

    def _refresh_students(self):
        self.student_list.clear()
        t, c = self._selected_teacher, self._selected_class
        if (not t or not c or t not in self._data or c not in self._data[t]["classes"]): return
        for name in self._data[t]["classes"][c]:
            self.student_list.addItem(name)

    def _update_preview(self):
        self.preview_label.setStyleSheet("color: #64748b; margin-left: 12px;")
        teachers = len(self._data)
        classes = sum(len(t["classes"]) for t in self._data.values())
        students = sum(len(s) for t in self._data.values() for s in t["classes"].values())
        parts = []
        if teachers: parts.append(f"👨‍🏫 {teachers}老师")
        if classes: parts.append(f"🏫 {classes}班")
        if students: parts.append(f"🧑‍🎓 {students}学生")
        self.preview_label.setText("  |  ".join(parts) if parts else "请添加老师、班级、学生")

    # ── 注册 ──

    def _do_register(self):
        if not self._data:
            QMessageBox.warning(self, "提示", "请至少添加一个老师"); return
        tt = len(self._data)
        tc = sum(len(t["classes"]) for t in self._data.values())
        ts = sum(len(s) for t in self._data.values() for s in t["classes"].values())
        action = "保存更改" if self.mode == "manage" else "批量注册"
        msg = f"确认{action}？\n\n老师：{tt} 人\n班级：{tc} 个\n学生：{ts} 人"
        if self.mode == "manage":
            msg += "\n\n⚠ 这将覆盖现有班级数据"
        reply = QMessageBox.question(self, f"确认{action}", msg,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        self.register_btn.setEnabled(False)
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0)
        self.log_area.setVisible(True); self.log_area.clear()
        password = (self.pwd_input.text().strip() or "111111") if self.pwd_input else "111111"
        self._worker = RegisterWorker(self.backend_dir, self.data_dir, self._data, password, self.mode)
        self._worker.progress.connect(self._on_progress)
        self._worker.progress_pct.connect(self.progress_bar.setValue)
        self._worker.done_signal.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, msg: str):
        self.log_area.append(msg)

    def _on_done(self, success: int, fail: int):
        self.progress_bar.setVisible(False); self.register_btn.setEnabled(True)
        msg = f"{'保存' if self.mode == 'manage' else '注册'}完成！\n\n✅ 成功：{success} 人"
        if fail > 0: msg += f"\n❌ 失败：{fail} 人"
        QMessageBox.information(self, "完成", msg)
