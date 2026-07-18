"""
QC Launcher — 批量注册模块（v2.0）
通过 HTTP API 调用后端，不再直接操作数据库。
"""

import json
from collections import OrderedDict

import requests
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QLineEdit, QGroupBox, QMessageBox,
    QProgressBar, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, QEvent, QThread, Signal
from PySide6.QtGui import QFont

from .styles import (
    BTN_SECONDARY, INPUT_STYLE, LIST_STYLE,
    BTN_ORANGE, BTN_GREEN, BTN_ADD_SMALL, BTN_DEL_SMALL,
    PROGRESS_BAR, LOG_AREA, WARN_BAR,
)


# ============================================================
#  HTTP 工具
# ============================================================

def _get_api_base() -> str:
    """获取后端 API 地址（默认 localhost:8000）"""
    return "http://127.0.0.1:8000"


def _login_admin() -> str | None:
    """用 admin 账号登录，返回 token"""
    try:
        resp = requests.post(f"{_get_api_base()}/api/login",
                             json={"username": "admin", "password": "111111"},
                             timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("token")
    except Exception:
        pass
    return None


# ============================================================
#  注册工作线程（通过 HTTP API）
# ============================================================

class RegisterWorker(QThread):
    progress = Signal(str)
    done_signal = Signal(int, int)   # (success, fail)
    progress_pct = Signal(int)

    def __init__(self, data: OrderedDict, default_password: str, mode: str = "register"):
        super().__init__()
        self.data = data
        self.default_password = default_password
        self.mode = mode

    def run(self):
        # 1. 先登录获取 token
        self.progress.emit("🔑 正在登录后端...")
        token = _login_admin()
        if not token:
            self.progress.emit("❌ 无法连接后端或登录失败，请确保服务已启动")
            self.done_signal.emit(0, 0)
            return
        self.progress.emit("✅ 已连接后端")

        headers = {"Authorization": f"Bearer {token}"}
        api = _get_api_base()

        # 2. 构建批量注册数据
        users = []
        total_teachers = len(self.data)
        total_students = sum(len(s) for t in self.data.values() for s in t["classes"].values())
        total = total_teachers + total_students
        done = 0
        success = 0
        fail = 0

        def _pct():
            self.progress_pct.emit(int(done / max(total, 1) * 100))

        # 收集所有用户
        for tname in self.data:
            users.append({
                "username": tname,
                "password": self.default_password,
                "role": "teacher",
                "teacher": None
            })
            done += 1; _pct()

            for cname, snames in self.data[tname]["classes"].items():
                for sname in snames:
                    sname = sname.strip()
                    if not sname:
                        continue
                    users.append({
                        "username": sname,
                        "password": self.default_password,
                        "role": "student",
                        "teacher": tname
                    })
                    done += 1; _pct()

        # 3. 调用批量注册 API
        self.progress.emit(f"📤 正在批量注册 {len(users)} 个账号...")
        try:
            resp = requests.post(f"{api}/api/admin/batch-register",
                                 json={"users": users, "default_password": self.default_password},
                                 headers=headers,
                                 timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                success = result.get("success", 0)
                fail = result.get("fail", 0)
                skip = result.get("skip", 0)
                for detail in result.get("details", []):
                    status = detail.get("status", "")
                    username = detail.get("username", "")
                    msg = detail.get("msg", "")
                    if status == "success":
                        self.progress.emit(f"✅ {username}: {msg}")
                    elif status == "skip":
                        self.progress.emit(f"⏭️  {username}: {msg}")
                    else:
                        self.progress.emit(f"❌ {username}: {msg}")
                self.progress.emit(f"\n📊 完成：成功 {success}，跳过 {skip}，失败 {fail}")
            else:
                error_msg = resp.json().get("detail", resp.text)
                self.progress.emit(f"❌ 注册失败: {error_msg}")
                fail = len(users)
        except requests.exceptions.ConnectionError:
            self.progress.emit("❌ 无法连接后端，请确保服务已启动")
            fail = len(users)
        except Exception as e:
            self.progress.emit(f"❌ 注册异常: {e}")
            fail = len(users)

        # 4. 保存班级数据
        if self.mode != "manage":
            self.progress.emit("📁 正在保存班级数据...")
            for tname, tdata in self.data.items():
                classes = []
                for cname, snames in tdata["classes"].items():
                    students = []
                    for sname in snames:
                        sname = sname.strip()
                        if sname:
                            students.append({"name": sname})
                    classes.append({"name": cname, "students": students})
                try:
                    resp = requests.post(f"{api}/api/admin/classes/{tname}",
                                         json={"classes": classes},
                                         headers=headers,
                                         timeout=10)
                    if resp.status_code == 200:
                        self.progress.emit(f"✅ 班级数据已保存: {tname}")
                    else:
                        self.progress.emit(f"⚠️  班级保存失败: {tname}")
                except Exception as e:
                    self.progress.emit(f"⚠️  班级保存异常: {e}")

        self.done_signal.emit(success, fail)


# ============================================================
#  批量注册对话框
# ============================================================

class BatchRegisterDialog(QDialog):

    def __init__(self, parent=None, mode: str = "register"):
        super().__init__(parent)
        self.mode = mode
        self._worker = None
        self._data = OrderedDict()
        self._selected_teacher = None
        self._selected_class = None

        self.setWindowTitle("账号管理" if mode == "manage" else "账号注册")
        self.setMinimumSize(850, 520)
        self.resize(900, 560)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint | Qt.WindowCloseButtonHint
        )
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
        """通过 API 加载现有老师/班级/学生"""
        token = _login_admin()
        if not token:
            QMessageBox.warning(self, "错误", "无法连接后端，请确保服务已启动")
            return

        headers = {"Authorization": f"Bearer {token}"}
        api = _get_api_base()

        try:
            # 获取老师列表
            resp = requests.get(f"{api}/api/users", headers=headers, timeout=10)
            if resp.status_code == 200:
                users = resp.json().get("users", [])
                teachers = [u for u in users if u.get("role") == "teacher"]

                for t in teachers:
                    tname = t.get("username", "")
                    if not tname:
                        continue
                    self._ensure_teacher(tname)

                    # 获取该老师的班级
                    try:
                        resp2 = requests.get(f"{api}/api/admin/classes/{tname}",
                                            headers=headers, timeout=10)
                        if resp2.status_code == 200:
                            classes = resp2.json().get("classes", [])
                            for c in classes:
                                cname = c.get("name", "")
                                if not cname:
                                    continue
                                self._ensure_class(tname, cname)
                                for s in c.get("students", []):
                                    sname = s.get("name", "")
                                    if sname and sname not in self._data[tname]["classes"][cname]:
                                        self._data[tname]["classes"][cname].append(sname)
                    except Exception:
                        pass
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载数据失败: {e}")

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

        # 管理模式警告
        if self.mode == "manage":
            warn = QLabel("⚠ 请确保被编辑的老师账号不在线，否则多人同时操作会有数据丢失风险。")
            warn.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
            warn.setStyleSheet(WARN_BAR)
            warn.setWordWrap(True)
            layout.addWidget(warn)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False); self.progress_bar.setMaximumHeight(18)
        self.progress_bar.setStyleSheet(PROGRESS_BAR)
        layout.addWidget(self.progress_bar)

        # 日志
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True); self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setMaximumHeight(120); self.log_area.setVisible(False)
        self.log_area.setStyleSheet(LOG_AREA)
        layout.addWidget(self.log_area)

        # 按钮
        btn_row = QHBoxLayout(); btn_row.addStretch()
        if self.mode == "manage":
            label, style = "保存更改", BTN_ORANGE
        else:
            label, style = "开始注册", BTN_GREEN
        self.register_btn = QPushButton(label)
        self.register_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.register_btn.setStyleSheet(style)
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
        add_btn = QPushButton("➕")
        add_btn.setFixedSize(26, 26)
        add_btn.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        add_btn.setStyleSheet(BTN_ADD_SMALL)
        add_btn.clicked.connect(add_action)
        row.addWidget(add_btn)
        del_btn = QPushButton("❌")
        del_btn.setFixedSize(26, 26)
        del_btn.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        del_btn.setStyleSheet(BTN_DEL_SMALL)
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
        self._worker = RegisterWorker(self._data, password, self.mode)
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
