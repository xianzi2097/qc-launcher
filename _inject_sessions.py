"""注入测试课堂数据"""
import json, os, random
from datetime import datetime, timedelta

teachers_dir = r'c:\Arin - cabin\QC-PocketSpace\data\users\teachers'
if not os.path.exists(teachers_dir):
    print('data 目录不存在')
    exit()

for tid in os.listdir(teachers_dir):
    info_path = os.path.join(teachers_dir, tid, 'info.json')
    if not os.path.exists(info_path):
        continue
    with open(info_path, 'r', encoding='utf-8') as f:
        info = json.load(f)
    if info.get('username') != '林老师(t)':
        continue

    classes_path = os.path.join(teachers_dir, tid, 'classes.json')
    with open(classes_path, 'r', encoding='utf-8') as f:
        classes = json.load(f)

    target = None
    for c in classes:
        if c['name'] == 'Scratch启蒙班':
            target = c
            break
    if not target:
        print('Scratch启蒙班 未找到')
        exit()

    students = target['students']
    names = {s['user_id']: s['name'] for s in students}

    records = []
    start = datetime(2026, 3, 1)
    topics = [
        '认识Scratch界面', '移动和旋转积木', '绘制基本图形', '颜色和背景',
        '键盘控制角色', '碰撞检测', '变量和计数', '条件和判断',
        '循环结构', '克隆技术', '消息广播', '数学运算积木',
        '字符串处理', '列表的使用', '自制积木', '画笔功能',
        '音乐和音效', '计时器', '鼠标跟随', '图层和层次',
        '角色动画', '场景切换', '游戏计分', '关卡设计',
        '数组和遍历', '函数封装', '调试技巧', '项目规划',
        'UI设计基础', '作品展示'
    ]

    for i in range(30):
        date = (start + timedelta(weeks=i)).strftime('%Y-%m-%d')
        month = date[:7]
        attrs = ['present'] * 5 + ['absent'] * 1 + ['present'] * 4

        student_records = []
        for sid, sname in names.items():
            status = random.choice(attrs)
            student_records.append({
                'id': str(sid),
                'name': sname,
                'status': status,
                'content': f'学习了{topics[i % len(topics)]}，完成了课堂练习' if status == 'present' else '',
                'remark': '' if status == 'present' else '请假',
                'next_plan': ''
            })

        month_file = os.path.join(teachers_dir, tid, 'sessions', 'Scratch启蒙班', f'{month}.json')
        os.makedirs(os.path.dirname(month_file), exist_ok=True)

        month_records = []
        if os.path.exists(month_file):
            with open(month_file, 'r', encoding='utf-8') as f:
                month_records = json.load(f)

        month_records.append({'date': date, 'students': student_records})
        month_records.sort(key=lambda x: x['date'], reverse=True)

        with open(month_file, 'w', encoding='utf-8') as f:
            json.dump(month_records, f, ensure_ascii=False, indent=2)

    print(f'Done: Scratch启蒙班 30 records')
    print(f'Students: {len(students)}')
    print(f'Range: {start.strftime("%Y-%m-%d")} ~ {(start + timedelta(weeks=29)).strftime("%Y-%m-%d")}')
    break
