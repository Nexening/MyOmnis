import flet as ft
import re
import datetime # 引入时间处理模块
import sqlite3
import json # 用于存取事件列表
import shutil # 用于复制文件
import os     # 用于处理路径
from pathlib import Path # 【新增】：用于智能获取全平台兼容路径

# 1. 主程序
def main(page: ft.Page):
    # --- 0. 全局辅助函数 ---
    # 获取当前主题下的颜色配置
    def get_app_colors():
        is_dark = page.theme_mode == "dark"
        return {
            "bg": "grey900" if is_dark else "grey100",      # 大背景
            "card": "grey800" if is_dark else "white",      # 卡片背景
            "text": "white" if is_dark else "black",        # 主要文字
            "sub_text": "grey400" if is_dark else "grey",   # 次要文字
            "icon": "white" if is_dark else "grey700",      # 图标
            "divider": "grey700" if is_dark else "grey200", # 分割线
            "input_bg": "grey900" if is_dark else "white",  # 输入框背景
            "orange": "orange400" if is_dark else "orange600", # 调整橙色亮度
            "blue": "blue400" if is_dark else "blue600",       # 调整蓝色亮度
            "shadow": "black" if is_dark else "black12"   # 浅色12 深色全黑
        }

    # 读取图标偏好 (默认为 star)
    # 选项: "star" 或 "bone"
    icon_preference = [page.client_storage.get("icon_preference") or "star"] 

    # 【新增】：读取排序偏好 (默认为 desc: 倒序/最新在前)
    # 选项: "desc" (倒序) 或 "asc" (正序)
    sort_preference = [page.client_storage.get("sort_preference") or "desc"]

    # App 基础设置
    page.title = "My Omnis"
    page.theme_mode = "light" 
    page.padding = 0 
    # page.bgcolor = "grey100" # 保持使用字符串颜色
    page.bgcolor = get_app_colors()["bg"] # 动态背景色

    
    # 【修复点】：删除了 page.theme 设置
    # Flet 0.22.1 的 Theme 组件比较简单，我们直接用默认主题，确保不报错
    
    # ---------------------------------------------------
    # 页面 1: 吞吞日志 (SQLite + Timeline + 动态主题版)
    # ---------------------------------------------------
    def get_log_view():
        colors = get_app_colors() # 获取动态颜色

        # --- 1. 数据库初始化 (安卓防闪退终极版) ---
        # 【修正2】：使用 Path.home() 获取跨平台可写路径
        # 在 Windows 上是 C:\Users\你\tuntun.db
        # 在 Android 上是 /data/user/0/com.tuntun/files/tuntun.db (可读写!)
        db_path = str(Path.home().joinpath("tuntun.db"))
        
        conn = sqlite3.connect(db_path, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_str TEXT,
                time_str TEXT,
                rating INTEGER,
                events TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # --- 2. 状态变量 ---
        # 默认选中今天
        today = datetime.datetime.now()
        current_view_month = [today.year, today.month] # 用于筛选视图 [年, 月]
        
        # 写入模式的状态
        write_date_val = [today.strftime("%d.%m.%Y")]
        write_time_val = [today.strftime("%H:%M")]
        write_rating = [0] # 0-5 星
        
        # --- 3. UI 控件定义 (预创建) ---
        
        # 3.1 顶部筛选器 (Filter)
        filter_label = ft.Text(f"{today.year}年 {today.month}月", size=18, weight="bold", color=colors["text"])
        
        # 3.2 列表容器 (Timeline) - 增加滚动监听
        log_list = ft.Column(
            scroll="hidden", 
            expand=True, 
            spacing=15,
            # 【核心修改】：当发生滚动时，把焦点强行给“记一笔”按钮(write_btn)，
            # 这样搜索框就会失去焦点，键盘收起，光标消失。
            on_scroll=lambda e: write_btn.focus() 
        )

        # 3.3 写入页面的控件
        # 日期/时间选择器 (复用 Overlay 逻辑)
        def on_log_date_change(e):
            if log_date_picker.value:
                d = log_date_picker.value.strftime("%d.%m.%Y")
                btn_date_display.text = d
                write_date_val[0] = d
                btn_date_display.update()
        
        def on_log_time_change(e):
            if log_time_picker.value:
                t = log_time_picker.value.strftime("%H:%M")
                btn_time_display.text = t
                write_time_val[0] = t
                btn_time_display.update()

        log_date_picker = ft.DatePicker(on_change=on_log_date_change)
        log_time_picker = ft.TimePicker(on_change=on_log_time_change)
        # 注意：Overlay 需要在 build 时确保不重复，这里先存着，等显示时挂载

        # 3.4 搜索框
        search_input = ft.TextField(
            hint_text="搜索记录...", 
            prefix_icon="search",
            border_radius=30, # 胶囊形状
            height=36, 
            content_padding=10, 
            text_size=14, 
            bgcolor=colors["card"], 
            border_color="grey300",
            # 输入变动时直接刷新列表
            on_change=lambda e: refresh_timeline() 
        )

        # 用于转移焦点的隐形按钮 (解决光标闪烁问题)
        dummy_focus_node = ft.IconButton(icon="check", visible=False) 
        # 注意：Visible=False 有时会导致无法聚焦，如果不行，可以用 width=0, opacity=0
        # 稳妥起见，我们直接聚焦到现有的 "记一笔" 按钮上，或者筛选器的箭头按钮上，这最简单。

        # --- 头像管理逻辑 ---
        # 1. 定义头像容器 (Ref) 方便更新内容
        avatar_content = ft.Ref[ft.Container]()

        def safe_delete_old_avatar():
            """安全删除旧头像文件"""
            old_path = page.client_storage.get("user_avatar")
            if old_path and os.path.exists(old_path):
                try:
                    os.remove(old_path) # 【核心】：物理删除文件
                    print(f"已删除旧文件: {old_path}")
                except Exception as e:
                    print(f"删除旧文件失败: {e}")
        
        def load_avatar():
            """从存储加载头像"""
            path = page.client_storage.get("user_avatar")
            if path and os.path.exists(path):
                return ft.Image(
                    src=path, # 不需要加 ?t=... 了，因为文件名变了
                    width=120, 
                    height=120, 
                    border_radius=60, 
                    fit=ft.ImageFit.COVER, # 居中填满，这就是目前的“自动裁剪”
                    error_content=ft.Icon("broken_image", size=40, color="grey400") 
                )
            else:
                return ft.Icon("pets", size=60, color="grey400")

        def update_avatar_view():
            """刷新头像显示"""
            if avatar_content.current:
                avatar_content.current.content = load_avatar()
                avatar_content.current.update()

        def on_avatar_picked(e: ft.FilePickerResultEvent):
            """图片选择回调 (自动清理 + 复制)"""
            if e.files:
                src_path = e.files[0].path
                
                try:
                    # 1. 先清理掉旧头像 (如果有的话)
                    # 必须在保存新文件之前删，防止万一新旧文件名一样导致冲突（虽然概率小）
                    safe_delete_old_avatar()

                    # 2. 准备新路径
                    # 使用时间戳作为文件名的一部分，彻底解决缓存不刷新的问题！
                    import time
                    _, ext = os.path.splitext(src_path)
                    # 例如: tuntun_avatar_1721534.jpg
                    new_filename = f"tuntun_avatar_{int(time.time())}{ext}"
                    dst_path = str(Path.home().joinpath(new_filename))
                    
                    # 3. 复制新文件
                    shutil.copy(src_path, dst_path)
                    
                    # 4. 更新存储和界面
                    page.client_storage.set("user_avatar", dst_path) 
                    update_avatar_view()
                    
                except Exception as ex:
                    page.snack_bar = ft.SnackBar(ft.Text(f"头像处理失败: {str(ex)}"), bgcolor="red")
                    page.snack_bar.open = True
                    page.update()
                
                page.dialog.open = False
                page.update()

        def remove_avatar(e):
            """恢复默认 (同时删除文件)"""
            # 1. 物理删除文件
            safe_delete_old_avatar()
            
            # 2. 移除存储记录
            page.client_storage.remove("user_avatar")
            
            # 3. 刷新界面
            update_avatar_view()
            page.dialog.open = False
            page.update()

        avatar_picker = ft.FilePicker(on_result=on_avatar_picked)
        # 【重要】稍后要把 avatar_picker 加入 overlay

        btn_date_display = ft.Text(today.strftime("%d.%m.%Y"), size=16, color=colors["blue"])
        btn_time_display = ft.Text(today.strftime("%H:%M"), size=16, color=colors["blue"])
        
        # 星星打分 (5个 IconButton)
        stars_row = ft.Row(spacing=5, alignment="center")
        
        # 事件输入框列表
        events_input_col = ft.Column(spacing=10)
        # 默认先加 3 个输入框
        for i in range(3):
            events_input_col.controls.append(
                ft.TextField(
                    hint_text=f"事件 {i+1}...", border_radius=10, 
                    content_padding=10, height=45, bgcolor=colors["card"], border_color="grey300"
                )
            )

        def show_avatar_options(e):
            """显示头像操作菜单 (按钮版)"""
            page.dialog = ft.AlertDialog(
                title=ft.Text("设置头像", size=18, weight="bold"),
                content=ft.Column([
                    # 按钮 1: 更换头像 (灰色底)
                    ft.Container(
                        bgcolor="grey200", border_radius=8, padding=12,
                        on_click=lambda _: avatar_picker.pick_files(allow_multiple=False, file_type="image"),
                        content=ft.Row([
                            ft.Icon("image", color="black"),
                            ft.Text("更换头像", size=16, color="black")
                        ], alignment="center")
                    ),
                    ft.Container(height=10), # 按钮间距
                    # 按钮 2: 恢复默认 (红色浅底)
                    ft.Container(
                        bgcolor="red50", border_radius=8, padding=12,
                        on_click=remove_avatar,
                        content=ft.Row([
                            ft.Icon("delete", color="red"),
                            ft.Text("恢复默认", size=16, color="red")
                        ], alignment="center")
                    )
                ], tight=True, spacing=0),
            )
            page.dialog.open = True
            page.update()

        # --- 4. 逻辑函数 ---
        def refresh_timeline():
            """从数据库读取数据并渲染时间轴 (SQL 优化 + 智能排序版)"""
            log_list.controls.clear()
            
            # 1. 获取状态
            y, m = current_view_month
            keyword = search_input.value.strip() # 去除首尾空格
            
            # 【新增】：确定排序方向
            # 如果偏好是 desc，则用 DESC (大到小，最新的在前)
            # 如果偏好是 asc，则用 ASC (小到大，最旧的在前)
            sort_sql = "ASC" if sort_preference[0] == "asc" else "DESC"
            
            # 【核心黑魔法】：构建按真实时间排序的 SQL 片段
            # 将 "dd.mm.yyyy" 转换为 "yyyy-mm-dd" 进行排序，同时拼上时间
            # substr(date_str, 7, 4) = yyyy
            # substr(date_str, 4, 2) = mm
            # substr(date_str, 1, 2) = dd
            order_clause = f"ORDER BY substr(date_str, 7, 4) || substr(date_str, 4, 2) || substr(date_str, 1, 2) || time_str {sort_sql}"

            # 2. 根据是否有搜索词，决定查什么数据
            if keyword:
                # A. 搜索模式：全库搜索
                search_term = f"%{keyword}%"
                cursor.execute(
                    f"SELECT * FROM logs WHERE date_str LIKE ? OR events LIKE ? {order_clause}", 
                    (search_term, search_term)
                )
            else:
                # B. 浏览模式：只查当前月份
                month_pattern = f"%.{m:02d}.{y}"
                cursor.execute(
                    f"SELECT * FROM logs WHERE date_str LIKE ? {order_clause}", 
                    (month_pattern,)
                )

            rows = cursor.fetchall()
            
            has_data = False
            display_count = 0 # 计数器

            for row in rows:
                # row: (id, date_str, time_str, rating, events_json, created_at)
                rid, d_str, t_str, rating, ev_json, _ = row
                
                # 因为上面的 SQL 语句已经帮我们筛选好了，能流到这里的 row 绝对是合法的。
                # 标记有数据，并计数
                has_data = True
                display_count += 1

                # 解析事件
                try:
                    ev_list = json.loads(ev_json)
                except: ev_list = []
                
                # 构建卡片 UI
                # 1. 头部：日期 + 时间 + 星星
                # 【修改点】：根据设置显示星星或骨头
                icon_char = "🦴" if icon_preference[0] == "bone" else "⭐"
                star_display = (icon_char * rating) if rating > 0 else "🈚️"
                
                # 2. 事件列表 UI
                event_items = []
                for idx, ev_text in enumerate(ev_list):
                    event_items.append(
                        ft.Row([
                            ft.Container(width=6, height=6, border_radius=3, bgcolor=colors["orange"], margin=ft.margin.only(top=5)),
                            ft.Text(ev_text, size=14, color=colors["text"], expand=True)
                        ], alignment="start", vertical_alignment="start")
                    )
                
                if not event_items:
                    event_items.append(ft.Text("（无特殊事件）", size=12, color=colors["sub_text"]))

                # 3. 组装单张卡片
                card = ft.Container(
                    padding=ft.padding.only(left=20, top=15, right=15, bottom=15),
                    bgcolor=colors["card"], border_radius=12,
                    shadow=ft.BoxShadow(blur_radius=5, color=colors["shadow"]),
                    # 绑定长按动作
                    on_long_press=lambda e, lid=rid: show_delete_confirm(lid),
                    content=ft.Column([
                        ft.Row([
                            ft.Text(f"{d_str}", size=16, weight="bold", color=colors["blue"]),
                            ft.Text(f"{t_str}", size=14, color=colors["sub_text"]),
                            ft.Container(expand=True), # 占位
                            ft.Text(star_display, size=14, color=colors["text"])
                        ], alignment="spaceBetween"),
                        ft.Divider(height=1, color="grey100"),
                        ft.Column(event_items, spacing=5)
                    ])
                )
                log_list.controls.append(card)

            # 【新增】：如果列表中有数据，且数据量超过3条(避免太少也显示)，在最后追加一个透明提示
            if has_data and display_count > 3:
                log_list.controls.append(
                    ft.Container(
                        content=ft.Text("- 已经到底啦！-", size=14, color=colors["sub_text"]), # 字号可以稍微调小一点显精致
                        alignment=ft.alignment.center,
                        padding=10,
                        opacity=0.8
                    )
                )

            if not has_data:
                log_list.controls.append(
                    ft.Container(
                        padding=50, alignment=ft.alignment.center,
                        content=ft.Column([
                            ft.Icon("inbox", size=50, color="grey300"),
                            ft.Text("本月没有吞吞的记录哦", color=colors["sub_text"])
                        ], horizontal_alignment="center")
                    )
                )
            
            # 【核心修复】：只有当 log_list 已经在页面上时，才调用 update()
            # 第一次加载时，log_list.page 是 None，所以这行不会执行，避免报错
            # 但数据已经塞进 log_list.controls 了，所以稍后页面渲染时会自动显示
            if log_list.page:
                log_list.update()

        def change_month(delta):
            """切换月份"""
            y, m = current_view_month
            m += delta
            if m > 12:
                m = 1
                y += 1
            elif m < 1:
                m = 12
                y -= 1
            current_view_month[0] = y
            current_view_month[1] = m
            filter_label.value = f"{y}年 {m}月"
            filter_label.update()
            refresh_timeline()

        def show_write_modal(e):
            """显示写日记的界面 (覆盖层/切换视图)"""
            # 这里简单处理：切换 visibility
            timeline_view.visible = False
            write_view.visible = True

            # 挂载 picker
            if log_date_picker not in page.overlay: page.overlay.append(log_date_picker)
            if log_time_picker not in page.overlay: page.overlay.append(log_time_picker)
            # 【新增】：挂载文件选择器
            if avatar_picker not in page.overlay: page.overlay.append(avatar_picker)

            update_avatar_view() # 每次打开确保显示最新头像
            page.update()

        def close_write_modal(e):
            write_view.visible = False
            timeline_view.visible = True
            page.update()

        def update_star_ui(score):
            """更新评分组件 (支持星星/骨头Emoji)"""
            write_rating[0] = score
            mode = icon_preference[0]

            stars_row.controls.clear()
            for i in range(1, 6):
                if mode == "bone":
                    # === 骨头模式 (Emoji版) ===
                    is_active = i <= score
                    
                    # 【核心修改】：不依赖图片文件，直接用 Emoji
                    # 激活状态：完全显示 (opacity=1.0)
                    # 未激活状态：半透明 (opacity=0.25)，模拟“空心/未填色”的效果
                    op = 1.0 if is_active else 0.25
                    
                    stars_row.controls.append(
                        ft.Container(
                            content=ft.Text("🦴", size=28), # 稍微大一点，可爱
                            opacity=op, # 通过透明度实现“亮/灭”效果
                            on_click=lambda e, s=i: update_star_ui(s),
                            padding=5,
                            border_radius=50,
                            ink=True, # 点击水波纹
                            # 增加一个透明背景，扩大点击热区，防止点不到
                            bgcolor=ft.colors.with_opacity(0.01, "white") 
                        )
                    )
                else:
                    # === 星星模式 (图标) ===
                    color = "pink300" if i <= score else "grey300"
                    stars_row.controls.append(
                        ft.IconButton(
                            icon="star", icon_size=32, icon_color=color,
                            style=ft.ButtonStyle(padding=0),
                            on_click=lambda e, s=i: update_star_ui(s)
                        )
                    )
            
            if stars_row.page:
                stars_row.update()

        # --- 新增：事件行管理逻辑 ---
        def reset_event_rows():
            """重置事件输入框：清空内容并恢复为3行"""
            events_input_col.controls.clear()
            for i in range(3):
                events_input_col.controls.append(
                    ft.TextField(hint_text=f"事件 {i+1}...", border_radius=10, content_padding=10, height=45, bgcolor=colors["card"], border_color="grey300")
                )
            if events_input_col.page:
                events_input_col.update()

        def add_event_line(e):
            """添加一行事件 (限制最大5行)"""
            current_count = len(events_input_col.controls)
            if current_count < 5:
                events_input_col.controls.append(
                    ft.TextField(hint_text=f"事件 {current_count+1}...", border_radius=10, content_padding=10, height=45, bgcolor=colors["card"], border_color="grey300")
                )
                events_input_col.update()
                
                # 如果加到了5个，提示一下 (可选)
                if current_count + 1 == 5:
                    page.snack_bar = ft.SnackBar(ft.Text("单次事件记录上限为 5 条"), bgcolor="orange")
                    page.snack_bar.open = True
                    page.update()
            else:
                page.snack_bar = ft.SnackBar(ft.Text("最多只能记录 5 件事哦"), bgcolor="red")
                page.snack_bar.open = True
                page.update()

        def save_log(e):
            """保存到数据库"""
            # 收集事件
            valid_events = []
            for txt_field in events_input_col.controls:
                val = txt_field.value.strip()
                if val: valid_events.append(val)
            
            # 存入库
            try:
                cursor.execute(
                    "INSERT INTO logs (date_str, time_str, rating, events) VALUES (?, ?, ?, ?)",
                    (write_date_val[0], write_time_val[0], write_rating[0], json.dumps(valid_events, ensure_ascii=False))
                )
                conn.commit()
                
                # 清空输入，复原其他
                for txt_field in events_input_col.controls: txt_field.value = ""
                reset_event_rows()
                update_star_ui(0)
                
                # 返回列表并刷新
                close_write_modal(None)
                refresh_timeline()
                
                # 简单提示
                page.snack_bar = ft.SnackBar(ft.Text("记录成功！吞吞+1 ❤️"), bgcolor="green")
                page.snack_bar.open = True
                page.update()
                
            except Exception as ex:
                print(ex)

        # --- 删除确认逻辑 ---
        def delete_log_entry(log_id):
            """执行删除操作"""
            cursor.execute("DELETE FROM logs WHERE id=?", (log_id,))
            conn.commit()
            page.dialog.open = False # 关闭弹窗
            page.update()
            refresh_timeline() # 刷新列表
            page.snack_bar = ft.SnackBar(ft.Text("已删除一条记录", color="white"), bgcolor="red600")
            page.snack_bar.open = True
            page.update()

        def show_delete_confirm(log_id):
            """显示长按删除确认弹窗 (大字号版)"""
            page.dialog = ft.AlertDialog(
                # 【修改】：自定义标题字号
                title=ft.Text("确认删除?", size=26, weight="bold"),
                # 【修改】：自定义内容字号
                content=ft.Text("删除后无法恢复，确定要删除这条记录吗？", size=16),
                actions=[
                    # 【修改】：按钮改用 TextButton 并放大文字
                    ft.TextButton(content=ft.Text("取消", size=18), on_click=lambda e: setattr(page.dialog, 'open', False) or page.update()),
                    ft.TextButton(content=ft.Text("删除", size=18, color="red"), on_click=lambda e: delete_log_entry(log_id)),
                ],
                actions_alignment="end",
            )
            page.dialog.open = True
            page.update()

        # --- 5. 构建 Write View 的星星组件 (修复间距) ---
        stars_row.controls.clear()
        # 初始化时调用一次，确保根据当前偏好显示正确的星星/骨头
        update_star_ui(0)

        # --- 6. 视图组装 ---
        write_btn = ft.ElevatedButton(
            content=ft.Row([
                ft.Icon("edit", size=18, color="white"),
                ft.Text("记一笔", size=16, weight="bold", color="white")
            ], alignment="center", spacing=5),
            style=ft.ButtonStyle(bgcolor=colors["orange"], color="white", elevation=10),
            height=45,
            on_click=show_write_modal
        )
        
        # A. 时间轴视图 (Timeline)
        timeline_view = ft.Column(
            expand=True,
            controls=[
                # 顶部筛选栏
                ft.Container(
                    bgcolor=colors["card"],
                    #margin=ft.margin.only(top=50, left=0, right=0, bottom=15),
                    # 【核心修改 2】：移除 top margin，只保留底部的间距
                    padding=ft.padding.only(top=50, left=15, right=15, bottom=20),
                    margin=ft.margin.only(bottom=10),
                    # border_radius=15, # 可以不要圆角
                    shadow=ft.BoxShadow(blur_radius=10, color=colors["shadow"]),
                    content=ft.Row([
                        ft.IconButton("arrow_back_ios", icon_size=16, on_click=lambda e: change_month(-1), icon_color=colors["icon"]),
                        filter_label,# 中间的日期文字
                        ft.IconButton("arrow_forward_ios", icon_size=16, on_click=lambda e: change_month(1), icon_color=colors["icon"]),
                        ft.Container(expand=True),
                        write_btn
                    ], alignment="center")
                ),

                # ... (顶部筛选栏 Container) ...
                
                # 【新增】：搜索框容器
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=15),
                    content=search_input
                ),
        
                # 列表区域
                ft.Container(
                    expand=True, padding=10,
                    content=log_list
                )
            ]
        )

        # B. 写入视图 (Write Form) - 模仿原版 EXE 布局
        write_view = ft.Column(
            visible=False, expand=True,
            controls=[
                # 顶部
                ft.Container(
                    padding=ft.padding.only(top=35, left=15, bottom=10),
                    bgcolor=colors["card"],
                    shadow=ft.BoxShadow(blur_radius=10, color=colors["shadow"]),
                    content=ft.Row([
                        ft.IconButton("close", icon_size=26, on_click=close_write_modal, icon_color=colors["icon"]),
                        ft.Text("记录吞吞的生活", size=20, weight="bold", color=colors["text"]),
                        ft.Container(expand=True),
                        # 【修改点 1】：保存按钮往左移 (增加右边距)
                        ft.Container(
                            margin=ft.margin.only(right=15), # 往左挤 15px
                            content=ft.ElevatedButton(
                                content=ft.Text("保存", size=16, weight="bold", color="white"),
                                on_click=save_log,
                                height=40,
                                style=ft.ButtonStyle(bgcolor=colors["blue"], color="white", elevation=10)
                            )
                        )
                    ])
                ),
                # 表单内容
                ft.Column(
                    scroll="hidden", expand=True, spacing=20,
                    controls=[
                        # 1. 狗狗图片 (支持长按更换)
                        ft.Container(
                            alignment=ft.alignment.center,
                            margin=ft.margin.only(top=10),
                            content=ft.Container(
                                ref=avatar_content, # 绑定 Ref
                                width=120, height=120, bgcolor="grey200", border_radius=60,
                                content=load_avatar(), # 初始加载
                                border=ft.border.all(4, colors["orange"]),
                                on_long_press=show_avatar_options # 【核心】：绑定长按
                            )
                        ),
                        
                        # 2. 日期时间选择
                        ft.Container(
                            padding=20, margin=ft.margin.symmetric(horizontal=20),
                            bgcolor=colors["card"], border_radius=15,
                            content=ft.Column([
                                ft.Text("时间信息", size=18, weight="bold", color=colors["sub_text"]),
                                ft.Container(height=2),
                                ft.Row([
                                    ft.Icon("calendar_month", color=colors["blue"]),
                                    ft.Text("日期:", size=18, color=colors["text"]),
                                    ft.Container(
                                        content=btn_date_display,
                                        on_click=lambda _: log_date_picker.pick_date(),
                                        padding=5
                                    )
                                ], alignment="start"),
                                ft.Divider(height=1, color="grey100"),
                                ft.Row([
                                    ft.Icon("access_time", color=colors["blue"]),
                                    ft.Text("时间:", size=18, color=colors["text"]),
                                    ft.Container(
                                        content=btn_time_display,
                                        on_click=lambda _: log_time_picker.pick_time(),
                                        padding=5
                                    )
                                ], alignment="start"),
                            ])
                        ),

                        # 3. 乖巧度
                        ft.Container(
                            padding=10, margin=ft.margin.symmetric(horizontal=20),
                            bgcolor=colors["card"], border_radius=15,
                            content=ft.Column([
                                ft.Text("今天乖不乖?", size=18, weight="bold", color=colors["sub_text"]),
                                ft.Container(height=2),
                                stars_row # 放入星星组件
                            ], horizontal_alignment="center")
                        ),

                        # 4. 事件列表
                        ft.Container(
                            padding=20, margin=ft.margin.symmetric(horizontal=20),
                            bgcolor=colors["card"], border_radius=15,
                            content=ft.Column([
                                ft.Text("吞吞发生了什么?", size=18, weight="bold", color=colors["sub_text"]),
                                ft.Container(height=2),
                                events_input_col,
                                # 【修改点 4】：绑定新的添加函数 (限制5行)
                                ft.TextButton(
                                    content=ft.Text("+ 再加一行", size=16, color=colors["blue"]),
                                    on_click=add_event_line, # 绑定新函数
                                )
                            ])
                        ),
                        ft.Container(height=50) # 底部垫高
                    ]
                )
            ]
        )

        # 初始化加载一次数据
        refresh_timeline()
        reset_event_rows()

        # 返回 Stack 结构，包含两个视图
        return ft.Stack(expand=True, controls=[timeline_view, write_view])

    # ---------------------------------------------------
    # 页面 2: 工具箱 (修复版：严格顺序 + 补全缺失函数 + 动态主题)
    # ---------------------------------------------------
    def get_tools_view():
        colors = get_app_colors() # 获取动态颜色

        # --- 1. 初始化主容器 ---
        tools_layout = ft.Column(expand=True, spacing=0)

        # 定义一个状态列表，记录当前在哪里
        # "menu" = 菜单页, "tool" = 工具页
        current_view_status = ["menu"]

        # --- 2. 侧边手势返回逻辑 ---
        def on_keyboard(e: ft.KeyboardEvent):
            if e.key == "Back":
                # 如果当前是在工具页，则拦截返回键，执行回到菜单
                if current_view_status[0] == "tool":
                    show_menu()
                    # 注意：Flet 0.22.1 在安卓上只要绑定了事件通常就会拦截退出
                    # 如果仍然退出，说明事件没捕获到，但通常这就够了
                else:
                    # 如果在菜单页，什么都不做，让系统执行默认的退出操作
                    pass
        
        # 【关键】：必须把这个函数绑定给 page
        page.on_keyboard_event = on_keyboard

        # --- 3. 状态与 Overlay 初始化 (必须最先执行) ---
        page.overlay.clear() # 清除旧的防止叠加
        
        # 搬家助手：日历/时间回调
        def on_date_change(e):
            if date_picker.value:
                date_input.value = date_picker.value.strftime("%d.%m.%Y")
                update_move_preview(None)
                page.update()
        
        def on_time_change(e):
            if time_picker.value:
                time_input.value = time_picker.value.strftime("%H:%M")
                update_move_preview(None)
                page.update()

        date_picker = ft.DatePicker(on_change=on_date_change)
        time_picker = ft.TimePicker(on_change=on_time_change)
        page.overlay.extend([date_picker, time_picker])

        # 搬家助手：帮手状态
        helper_value = ["m.T."]

        # --- 3. 定义所有 UI 控件 (必须在逻辑函数之前) ---
        
        # === A. 百度网盘清洗控件 ===
        DEFAULT_PREFIX = "复制并打开"
        DEFAULT_SUFFIX = (
            "责任说明：因官方持续随机出新题，题库无法做到100%覆盖。"
            "个人考试行为和能力无法控制，题库是帮助您降低学习压力，提高通过可能性的工具，而不是通过的绝对保证。"
            "“最新”定义为买家个人整理资料的编辑时间为最新。"
        )
        prefix_field = ft.TextField(label="前缀文字", value=DEFAULT_PREFIX, height=40, text_size=14, content_padding=10, border_color="grey300", bgcolor=colors["input_bg"])
        suffix_field = ft.TextField(label="免责声明后缀", value=DEFAULT_SUFFIX, multiline=True, min_lines=3, text_size=12, content_padding=10, border_color="grey300", bgcolor=colors["input_bg"])
        
        # 【重要】cleaner_input 必须在这里定义
        cleaner_input = ft.TextField(multiline=True, min_lines=3, max_lines=5, hint_text="直接粘贴整段百度网盘分享口令...", bgcolor=colors["input_bg"], border_color="transparent", text_size=14, content_padding=10)
        cleaner_output = ft.TextField(multiline=True, read_only=True, value="", min_lines=6, text_style=ft.TextStyle(color=colors["text"], size=14), bgcolor=colors["input_bg"], border_color="transparent", content_padding=10)
        cleaner_feedback = ft.Text(value="", color="green600", size=14, weight="bold", text_align="center")
        
        # === B. 搬家助手控件 (V7.3 修复版) ===
        
        # 1. 日期控件组 (输入框 + 按钮)
        # 【核心修复】：允许手动输入 (移除 read_only)，并移除 on_click 避免冲突
        date_input = ft.TextField(
            label="日期", hint_text="dd.mm.yyyy",
            expand=True, height=40, content_padding=10, text_size=14, 
            border_color="grey300", 
            text_align="center",
            border_radius=8, # 【新增】：圆角
            bgcolor=colors["input_bg"]
            # on_change=update_move_preview # 手动输入也能实时更新预览
        )
        # 独立的日期选择按钮 (绝对能点)
        date_button = ft.IconButton(
            icon="calendar_month", 
            icon_color=colors["orange"], 
            on_click=lambda _: date_picker.pick_date()
        )

        # 2. 时间控件组 (输入框 + 按钮)
        time_input = ft.TextField(
            label="时间", hint_text="HH:MM", 
            expand=True, height=40, content_padding=10, text_size=14, 
            border_color="grey300", 
            text_align="center",
            border_radius=8, # 【新增】：圆角
            bgcolor=colors["input_bg"]
            # on_change=update_move_preview
        )
        time_button = ft.IconButton(
            icon="access_time", 
            icon_color=colors["orange"], 
            on_click=lambda _: time_picker.pick_time()
        )

        # 3. 地址输入 (保持不变)
        start_addr_input = ft.TextField(
            hint_text="起点地址...", expand=True, height=50, text_size=14, 
            content_padding=10, border_color="grey300",
            border_radius=8, # 【新增】
            bgcolor=colors["input_bg"]
        )

        end_addr_input = ft.TextField(
            hint_text="终点地址...", expand=True, height=50, text_size=14, 
            content_padding=10, border_color="grey300",
            border_radius=8, # 【新增】
            bgcolor=colors["input_bg"]
        )

        # 4. 价格与趟数 (大字号版)
        price_input = ft.TextField(
            label="价格", suffix_text="€", 
            value="90", #显示预设值
            expand=1, 
            height=50, # 【修改点】：高度增加
            content_padding=10, 
            text_size=20, # 【修改点】：字号加大
            border_color="grey300", keyboard_type="number", 
            text_align="center",
            border_radius=8,
            bgcolor=colors["input_bg"]
        )
        trips_input = ft.TextField(
            label="趟数", suffix_text="x", 
            expand=1, 
            height=50, # 【修改点】：高度增加
            content_padding=10, 
            text_size=20, # 【修改点】：字号加大
            border_color="grey300", keyboard_type="number", value="1",
            text_align="center",
            border_radius=8,
            bgcolor=colors["input_bg"]
        )

        # 5. 选项 (保持不变)
        is_temp_booking = ft.Checkbox(label="临时预定 (不接受取消/更改)", value=False)
        has_big_furniture = ft.Checkbox(label="大件家具 (显示提示)", value=False)

        # 预览/反馈
        move_preview_text = ft.Text(value="", font_family="monospace", size=13, color=colors["text"], selectable=True)
        move_feedback_text = ft.Text(value="", color="green600", size=14, weight="bold", text_align="center")

        # --- 4. 定义逻辑函数 (必须在控件之后，视图之前) ---

        # === A. 清洗逻辑 ===
        def clean_link(e):
            raw_text = cleaner_input.value
            if not raw_text:
                cleaner_output.value = ""
                page.update()
                return
            match = re.search(r"https://pan\.baidu\.com[^\s]*", raw_text)
            if match:
                url = match.group(0)
                cleaner_output.value = f"{prefix_field.value}\n链接:{url}\n\n\n{suffix_field.value}"
            else:
                cleaner_output.value = "❌ 未检测到有效的百度网盘链接..."
            page.update()

        def paste_and_clean(e):
            try:
                clip_text = page.get_clipboard()
                if clip_text:
                    cleaner_input.value = clip_text
                    clean_link(None)
                page.update()
            except: pass

        def restore_defaults(e):
            prefix_field.value = DEFAULT_PREFIX
            suffix_field.value = DEFAULT_SUFFIX
            clean_link(None)
            page.update()

        # 【修复点】：你之前漏掉了这个函数，导致 NameError
        def copy_cleaner_result(e):
            if cleaner_output.value and "❌" not in cleaner_output.value:
                page.set_clipboard(cleaner_output.value)
                cleaner_feedback.value = "✅ 已成功复制到剪贴板"
            else:
                cleaner_feedback.value = "⚠️ 没有内容可复制"
            page.update()
        
        # 绑定清洗事件
        cleaner_input.on_change = clean_link
        prefix_field.on_change = clean_link
        suffix_field.on_change = clean_link

        # === B. 搬家逻辑 ===
        def update_move_preview(e):
            d_str = date_input.value or "dd.mm.yyyy"
            t_str = time_input.value or "xx:xx"
            h_str = helper_value[0]
            
            s_addr = start_addr_input.value or ""
            e_addr = end_addr_input.value or ""
            s_addr = re.sub(r'Aachen\s*$', 'AC', s_addr, flags=re.IGNORECASE)
            e_addr = re.sub(r'Aachen\s*$', 'AC', e_addr, flags=re.IGNORECASE)

            # 价格逻辑修改
            # 如果输入框是空的 (用户没填)，就取 "90"；如果填了，就用填的值
            price = price_input.value if price_input.value else "90"
            trips = trips_input.value or "1"

            if is_temp_booking.value:
                cancellation_text = "临时预定不接受取消/更改，"
            else:
                try:
                    dt = datetime.datetime.strptime(d_str, "%d.%m.%Y")
                    notify_dt = dt - datetime.timedelta(days=2)
                    cancellation_text = f"如有时间更改需要请于{notify_dt.day}号结束前通知，过后取消/更改需收取20%原标价。"
                except:
                    cancellation_text = "如有时间更改需要请于(dd-2)号结束前通知，过后取消/更改需收取20%原标价。"

            furniture_text = "如有大件请保证提前拆卸和通道畅通。" if has_big_furniture.value else ""

            move_preview_text.value = (
                f"🗓️ {d_str}   🕗 {t_str}   {h_str}\n\n"
                f"{s_addr}\n"
                f"➡ \n"
                f"{e_addr}\n\n\n"
                f"{price}€  {trips}x\n\n"
                f"_________________________________ \n"
                f"车型已确定，{cancellation_text}{furniture_text}如遇时间轻微变动以司机信息为准，敬请谅解。现场支持现金/PayPal付款。"
            )
            page.update()

        def copy_move_result(e):
            if move_preview_text.value:
                page.set_clipboard(move_preview_text.value)
                move_feedback_text.value = "✅ 已复制搬家信息"
            else:
                move_feedback_text.value = "⚠️ 信息为空"
            page.update()
        
        # 帮手切换逻辑 (需要在此处定义toggle_helper，因为它用到 update_move_preview)
        def toggle_helper(e):
            val = e.control.data
            helper_value[0] = val
            btn_mt.bgcolor = colors["orange"] if val == "m.T." else "grey200"
            btn_mt_content.color = "white" if val == "m.T." else "black"
            btn_ot.bgcolor = colors["orange"] if val == "o.T." else "grey200"
            btn_ot_content.color = "white" if val == "o.T." else "black"
            update_move_preview(None)
            page.update()

        # 定义帮手按钮 (逻辑之后)
        btn_mt_content = ft.Text("m.T. (有帮手)", color="white", weight="bold", size=16)
        btn_ot_content = ft.Text("o.T. (无帮手)", color="black", weight="bold", size=16)
        btn_mt = ft.Container(content=btn_mt_content, data="m.T.", expand=True, height=40, bgcolor=colors["orange"], border_radius=ft.border_radius.only(top_left=8, bottom_left=8), alignment=ft.alignment.center, on_click=toggle_helper)
        btn_ot = ft.Container(content=btn_ot_content, data="o.T.", expand=True, height=40, bgcolor="grey200", border_radius=ft.border_radius.only(top_right=8, bottom_right=8), alignment=ft.alignment.center, on_click=toggle_helper)
        helper_switch_row = ft.Row([btn_mt, btn_ot], spacing=1)

        # 绑定搬家事件
        for ctrl in [start_addr_input, end_addr_input, price_input, trips_input, is_temp_booking, has_big_furniture, date_input, time_input]:
            ctrl.on_change = update_move_preview

        # --- 5. 视图组装 (卡片工厂 & 路由函数) ---
        def make_card(content_ctrl, border_color="transparent", padding_val=15):
            border_arg = None
            if border_color != "transparent":
                border_arg = ft.border.all(2, border_color)
            return ft.Container(
                content=content_ctrl, bgcolor=colors["card"], padding=padding_val, border_radius=12, border=border_arg,
                shadow=ft.BoxShadow(spread_radius=1, blur_radius=5, color=colors["shadow"])
            )
        
        # --- 增加数据重置逻辑 ---
        # 【修改点2】：定义重置函数
        def reset_all_data():
            # 重置清洗工具
            cleaner_input.value = ""
            cleaner_output.value = ""
            cleaner_feedback.value = ""
            # 重置搬家助手
            date_input.value = ""
            time_input.value = ""
            start_addr_input.value = ""
            end_addr_input.value = ""
            price_input.value = ""
            trips_input.value = "1"
            is_temp_booking.value = False
            has_big_furniture.value = False
            move_feedback_text.value = "" # 清空搬家助手的反馈
            helper_value[0] = "m.T." # 重置帮手状态
            # 重置按钮样式
            btn_mt.bgcolor = colors["orange"]
            btn_mt_content.color = "white"
            btn_ot.bgcolor = "grey200"
            btn_ot_content.color = "black"
            
        # --- 增加安卓物理返回键支持 ---
        # 【修改点1】：监听键盘事件（安卓侧滑返回 = 键盘事件 "Back"）
        def on_keyboard(e: ft.KeyboardEvent):
            # 如果按下了返回键，且当前不是在菜单页（通过判断controls数量简单推断），则返回菜单
            if e.key == "Back": 
                # 这里简单判定：如果当前工具页有顶部栏（Blue/Orange），说明在子页面
                # 为了安全，直接调用 show_menu，它会重置界面
                show_menu()

        page.on_keyboard_event = on_keyboard

        # 1. 菜单页
        def show_menu(e=None):
            current_view_status[0] = "menu" # 标记为菜单页
            reset_all_data() # 【修改点2】：每次回到菜单时，清空数据
            tools_layout.controls = [
                ft.Container(height=50), # 避开刘海
                # 菜单卡片1
                ft.Container(
                    padding=20, margin=ft.margin.symmetric(horizontal=20),
                    bgcolor=colors["card"], border_radius=15, height=150,
                    shadow=ft.BoxShadow(blur_radius=10, color=colors["shadow"]),
                    content=ft.Row([
                        ft.Container(width=3), # 缩进
                        ft.Icon("cleaning_services", size=50, color=colors["blue"]),
                        ft.Container(width=1), # 缩进
                        ft.Column([
                            ft.Text("百度网盘链接清洗", size=22, weight="bold", color=colors["text"]),
                            ft.Text("自动格式化分享链接", size=16, color=colors["sub_text"])
                        ], spacing=2, alignment="center")
                    ], alignment="start"),
                    on_click=show_cleaner
                ),
                ft.Container(height=20),
                # 菜单卡片2
                ft.Container(
                    padding=20, margin=ft.margin.symmetric(horizontal=20),
                    bgcolor=colors["card"], border_radius=15, height=150,
                    shadow=ft.BoxShadow(blur_radius=10, color=colors["shadow"]),
                    content=ft.Row([
                        ft.Container(width=3), # 缩进
                        ft.Icon("local_shipping", size=50, color=colors["orange"]),
                        ft.Container(width=1), # 缩进
                        ft.Column([
                            ft.Text("搬家助手", size=22, weight="bold", color=colors["text"]),
                            ft.Text("生成搬家信息小结", size=16, color=colors["sub_text"])
                        ], spacing=2, alignment="center")
                    ], alignment="start"),
                    on_click=show_mover
                )
            ]
            page.update()

        # 2. 清洗工具页
        def show_cleaner(e):
            current_view_status[0] = "tool" # 标记为工具页
            tools_layout.controls = [
                # 顶部返回栏 (Top Margin 45)
                ft.Container(
                    bgcolor=colors["blue"], padding=10, margin=ft.margin.only(top=25, bottom=20),
                    content=ft.Row([
                        # 【核心修改】：用 Container 包裹 Icon 代替 IconButton
                        ft.Container(
                            content=ft.Icon("arrow_back", color="white"),
                            padding=12, # 增加内边距，扩大点击范围
                            on_click=show_menu, # 点击事件绑在容器上
                            border_radius=70, # 圆形点击反馈
                            ink=True # (可选) 增加点击水波纹效果
                        ),
                        ft.Text("百度网盘链接清洗", size=24, color="white", weight="bold")
                    ])
                ),
                # 滚动内容
                ft.Column(expand=True, scroll="hidden", controls=[
                    ft.Container(padding=ft.padding.symmetric(horizontal=20), content=make_card(
                        ft.ExpansionTile(
                            title=ft.Text("⚙️ 修改固定话术", size=13, weight="bold", color=colors["sub_text"]),
                            initially_expanded=False,
                            tile_padding=ft.padding.only(left=10, right=10, top=0, bottom=0),
                            controls_padding=ft.padding.only(top=10, bottom=10),
                            controls=[prefix_field, ft.Container(height=10), suffix_field, ft.Container(height=10), ft.TextButton("恢复默认话术", icon="restore", on_click=restore_defaults)]
                        ), padding_val=5
                    )),
                    ft.Container(height=5),
                    ft.Container(padding=ft.padding.symmetric(horizontal=20), content=make_card(ft.Column([
                        ft.Row([ft.Text("  步骤1: 粘贴原始分享文案", size=15, weight="bold", color=colors["text"]),
                                ft.ElevatedButton("粘贴并处理", icon="paste", on_click=paste_and_clean, height=36, width=140, style=ft.ButtonStyle(padding=0, bgcolor="blue50", color=colors["blue"], elevation=0))
                        ], alignment="spaceBetween"),
                        ft.Container(height=5), cleaner_input # 这里引用不会报错了，因为上面已经定义了
                    ]))),
                    ft.Container(height=5),
                    ft.Container(padding=ft.padding.symmetric(horizontal=20), content=make_card(ft.Column([
                        ft.Row([ft.Text("  步骤2: 复制发送", size=15, weight="bold", color=colors["text"]),
                                ft.Container(content=ft.Text("最终效果 (已加空行)", size=14, color="white", weight="bold", text_align="center"), bgcolor=colors["blue"], height=30, width=140, alignment=ft.alignment.center, padding=ft.padding.symmetric(horizontal=0, vertical=5), border_radius=20)
                        ], alignment="spaceBetween"),
                        ft.Container(height=5), cleaner_output
                    ]), border_color=colors["blue"])),
                    ft.Container(height=20)
                ]),
                # 底部按钮
                ft.Container(
                    bgcolor=colors["card"], padding=ft.padding.only(left=20, right=20, top=10, bottom=10),
                    shadow=ft.BoxShadow(blur_radius=10, color="black12", offset=ft.Offset(0, -5)),
                    content=ft.Column([
                        ft.Container(content=cleaner_feedback, alignment=ft.alignment.center, padding=ft.padding.only(bottom=2)),
                        ft.ElevatedButton(
                            content=ft.Row([ft.Icon("rocket_launch", color="white"), ft.Text("一键复制", size=20, weight="bold", color="white")], alignment="center", spacing=5),
                            on_click=copy_cleaner_result, # 这里引用不会报错了
                            height=60, width=float("inf"),
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), bgcolor=colors["blue"], color="white")
                        )
                    ], spacing=0)
                )
            ]
            page.update()

        # 3. 搬家工具页
        def show_mover(e):
            current_view_status[0] = "tool" # 标记为工具页
            update_move_preview(None)
            tools_layout.controls = [
                # 顶部返回栏 (Top Margin 45)
                ft.Container(
                    bgcolor=colors["orange"], padding=10, margin=ft.margin.only(top=25, bottom=20),
                    content=ft.Row([
                        # 【核心修改】：用 Container 包裹 Icon 代替 IconButton
                        ft.Container(
                            content=ft.Icon("arrow_back", color="white"),
                            padding=12, # 增加内边距，扩大点击范围
                            on_click=show_menu, # 点击事件绑在容器上
                            border_radius=70, # 圆形点击反馈
                            ink=True # (可选) 增加点击水波纹效果
                        ),
                        ft.Text("搬家助手", size=24, color="white", weight="bold")
                    ])
                ),
                ft.Column(expand=True, scroll="hidden", controls=[
                    # 预览卡片 (修复底部空白)
                    ft.Container(padding=ft.padding.symmetric(horizontal=20), content=make_card(ft.Column([
                        
                        # 顶部标题栏
                        ft.Row([
                            ft.Text("信息预览", size=15, weight="bold", color=colors["text"]), 
                            ft.ElevatedButton("复制文本", icon="copy", on_click=copy_move_result, height=36, style=ft.ButtonStyle(bgcolor=colors["orange"], color="white"))], alignment="spaceBetween"),
                        
                        ft.Container(height=10), # 标题和内容的间距
                        
                        # 内容区域
                        ft.Container(
                            content=move_preview_text, 
                            border=ft.border.only(left=ft.border.BorderSide(4, colors["orange"])), 
                            padding=ft.padding.only(left=15)
                        ),
                        
                        # 【核心修改】：移除之前这里的 Container(height=5)
                        # 【核心修改】：直接放反馈文字，它会自动紧贴
                        ft.Container(
                            content=move_feedback_text, 
                            alignment=ft.alignment.center,
                            # 如果有文字显示时，稍微给点上边距；没有文字时高度几乎为0
                            padding=ft.padding.only(top=5) 
                        )
                    ], spacing=0))), # 【关键】：显式设置 spacing=0，消除默认的大间距
                    
                    ft.Container(height=1),
                    # 表单
                    # 填写表单
                    ft.Container(padding=ft.padding.symmetric(horizontal=20), content=make_card(ft.Column([
                        # 【核心修改】：显式添加 spacing=0，消除默认间距
                        ft.Text("基础信息", size=15, weight="bold", color=colors["sub_text"]),
                        ft.Container(height=5), 
                        
                        # 日期行
                        ft.Row([date_input, date_button], spacing=5),
                        ft.Container(height=5), # 现在这里的 5 就是真实的 5px
                        
                        # 时间行
                        ft.Row([time_input, time_button], spacing=5),
                        ft.Container(height=10), 
                        
                        # 帮手切换
                        helper_switch_row, 
                        ft.Container(height=15), # 分区大间距
                        
                        # 地址栏
                        ft.Text("地址:  自动 AC", size=15, weight="bold", color=colors["sub_text"]),
                        ft.Container(height=10),
                        ft.Row([ft.Icon("location_on", color="green"), start_addr_input]),
                        ft.Container(height=10),
                        ft.Row([ft.Icon("location_on", color="red"), end_addr_input]),
                        ft.Container(height=15),
                        
                        # 价格与趟数
                        ft.Row([price_input, trips_input], spacing=10),
                        ft.Container(height=10),
                        
                        # 选项
                        ft.Container(content=is_temp_booking, bgcolor=colors["input_bg"], padding=2, border_radius=8),
                        ft.Container(height=5),
                        ft.Container(content=has_big_furniture, bgcolor=colors["input_bg"], padding=2, border_radius=8),
                    ], spacing=2))), # 【注意】：这里加上 spacing=0
                    ft.Container(height=50)
                ])
            ]
            page.update()

        # 启动显示
        show_menu()
        return tools_layout
        
    # ---------------------------------------------------
    # 页面 3: 设置 (V12: 动态主题 + 骨头开关 + 修复导出)
    # ---------------------------------------------------
    def get_settings_view():
        colors = get_app_colors() # 获取当前颜色
        is_dark = page.theme_mode == "dark"
        is_bone = icon_preference[0] == "bone"

        # --- 1. 文件处理 (修复：确保 Picker 始终在 Overlay) ---
        def on_export_result(e: ft.FilePickerResultEvent):
            if e.path:
                try:
                    shutil.copy("tuntun.db", e.path)
                    page.snack_bar = ft.SnackBar(ft.Text("✅ 备份成功！"), bgcolor="green")
                    page.snack_bar.open = True
                    page.update()
                except Exception as ex:
                    page.snack_bar = ft.SnackBar(ft.Text(f"❌ 失败: {ex}"), bgcolor="red")
                    page.snack_bar.open = True
                    page.update()

        def on_import_result(e: ft.FilePickerResultEvent):
            if e.files:
                try:
                    shutil.copy(e.files[0].path, "tuntun.db")
                    page.snack_bar = ft.SnackBar(ft.Text("✅ 恢复成功！请重启 App"), bgcolor="green")
                    page.snack_bar.open = True
                    page.update()
                except Exception as ex:
                    page.snack_bar = ft.SnackBar(ft.Text(f"❌ 失败: {ex}"), bgcolor="red")
                    page.snack_bar.open = True
                    page.update()

        export_picker = ft.FilePicker(on_result=on_export_result)
        import_picker = ft.FilePicker(on_result=on_import_result)
        # 【关键修复】：每次进入设置页都重新挂载，防止被其他页面清除
        page.overlay.extend([export_picker, import_picker])

        # --- 2. 切换逻辑 ---
        def toggle_theme(e):
            page.theme_mode = "dark" if e.control.value else "light"
            page.bgcolor = get_app_colors()["bg"] # 立即更新大背景
            page.update()
            # 强制重载当前页面以应用新颜色
            class DummyEvent:
                class Control: selected_index = 2
                control = Control()
            on_nav_change(DummyEvent())

        def toggle_sort_order(e):
            """切换排序方式"""
            val = "asc" if e.control.value else "desc"
            sort_preference[0] = val
            page.client_storage.set("sort_preference", val)
            page.update()
            # 不需要强制刷新页面，因为这只影响 Log 页，下次去 Log 页会自动刷新

        def toggle_icon_style(e):
            val = e.control.data
            icon_preference[0] = val
            page.client_storage.set("icon_preference", val)
            
            # 更新按钮视觉状态
            btn_star.bgcolor = colors["orange"] if val == "star" else colors["input_bg"]
            btn_star_content.color = "white" if val == "star" else colors["text"]
            btn_bone.bgcolor = colors["orange"] if val == "bone" else colors["input_bg"]
            btn_bone_content.color = "white" if val == "bone" else colors["text"]
            page.update()

        # --- 3. 骨头/星星 切换按钮组 ---
        btn_star_content = ft.Text("⭐ 星星", color="white" if not is_bone else colors["text"], weight="bold")
        btn_bone_content = ft.Text("🦴 骨头", color="white" if is_bone else colors["text"], weight="bold")
        
        btn_star = ft.Container(
            content=btn_star_content, data="star", expand=True, height=35,
            bgcolor=colors["orange"] if not is_bone else colors["input_bg"],
            border_radius=ft.border_radius.only(top_left=8, bottom_left=8),
            alignment=ft.alignment.center, on_click=toggle_icon_style,
            border=ft.border.all(1, colors["orange"])
        )
        btn_bone = ft.Container(
            content=btn_bone_content, data="bone", expand=True, height=35,
            bgcolor=colors["orange"] if is_bone else colors["input_bg"],
            border_radius=ft.border_radius.only(top_right=8, bottom_right=8),
            alignment=ft.alignment.center, on_click=toggle_icon_style,
            border=ft.border.all(1, colors["orange"])
        )
        icon_switch_row = ft.Row([btn_star, btn_bone], spacing=0)

        # --- 关于弹窗 ---
        def show_about(e):
            page.dialog = ft.AlertDialog(
                title=ft.Text("关于 My Omnis"),
                content=ft.Column([
                    ft.Image(src="icons/logo.png", width=60, height=60, error_content=ft.Icon("pets", size=60)),
                    ft.Text("\n版本: v1.0.0 (Alpha)"),
                    ft.Text("\n开发: Python 3.14 + Flet"),
                    ft.Text("\n专门为吞吞和她的铲屎官们开发的百宝箱工具\n记录每一个可爱瞬间！\n(顺带便捷她爹的工作流)"),
                ], tight=True, horizontal_alignment="center"),
                actions=[ft.TextButton("关闭", on_click=lambda _: setattr(page.dialog, 'open', False) or page.update())],
                actions_alignment="center"
            )
            page.dialog.open = True
            page.update()

        # --- 4. 辅助函数：设置卡片 (修复间距问题) ---
        def setting_card(title, controls):
            return ft.Container(
                bgcolor=colors["card"],
                margin=ft.margin.symmetric(horizontal=20),
                padding=ft.padding.symmetric(horizontal=25, vertical=15),
                border_radius=15,
                content=ft.Column([
                    ft.Text(title, weight="bold", size=16, color=colors["sub_text"]),
                    # 【核心修改】：在这里增加一点微小的间距(5px)，而不是像之前那样留太多
                    ft.Container(height=10), 
                    # 【核心修改】：controls 容器本身不留间距，由控件自己控制
                    ft.Column(controls, spacing=0) 
                ], spacing=0) # 【核心修改】：父容器 spacing=0，防止标题离得太远
            )

        return ft.Column(
            controls=[
                ft.Container(height=40),
                # 胶囊标题
                ft.Container(
                    content=ft.Text("⚙️ 设置", size=24, weight="bold", color="white"),
                    bgcolor=colors["blue"],
                    padding=ft.padding.symmetric(horizontal=120, vertical=10),
                    border_radius=20, margin=ft.margin.only(bottom=2),
                    shadow=ft.BoxShadow(blur_radius=10, color=ft.colors.with_opacity(0.4, colors["blue"]))
                ),
                ft.Container(height=3),
                
                # 外观设置
                setting_card("外观", [
                    # 1. 暗黑模式
                    ft.ListTile(
                        leading=ft.Icon("dark_mode", color=colors["icon"]),
                        title=ft.Text("暗黑模式", size=16, color=colors["text"]),
                        trailing=ft.Switch(value=is_dark, on_change=toggle_theme, active_color=colors["orange"]),
                        content_padding=0, # 贴边
                        dense=True, # 【核心修改】：紧凑模式，减少垂直高度
                    ),
                    # 间距
                    ft.Container(height=10), 

                    # 2. 排序开关
                    ft.ListTile(
                        leading=ft.Icon("sort", color=colors["icon"]),
                        title=ft.Text("时间正序排列 (旧->新)", size=16, color=colors["text"]),
                        # 开关打开 = asc (正序)，关闭 = desc (倒序/默认)
                        trailing=ft.Switch(value=(sort_preference[0] == "asc"), on_change=toggle_sort_order, active_color=colors["orange"]),
                        content_padding=0,
                        dense=True
                    ),

                    ft.Container(height=20),

                    ft.Row([
                        ft.Text("乖巧度图标:", size=16, color=colors["text"]),
                        ft.Container(width=20),
                        ft.Container(content=icon_switch_row, width=160)
                    ], alignment="spaceBetween")
                ]),

                # 数据管理
                setting_card("数据管理", [ # 这里的标题字号会自动应用上面的 size=16
                    ft.ListTile(
                        leading=ft.Icon("upload_file", color=colors["blue"]),
                        title=ft.Text("导出数据备份", color=colors["text"]),
                        subtitle=ft.Text("保存 .db 文件", size=12, color=colors["sub_text"]),
                        on_click=lambda _: export_picker.save_file(file_name="tuntun_backup.db"),
                        content_padding=0,
                        dense=True # 【修改】：紧凑
                    ),
                    # 分割线上下稍微留白一点点，或者直接设为0
                    ft.Divider(height=1, color=colors["divider"]), 
                    ft.ListTile(
                        leading=ft.Icon("download", color=colors["orange"]),
                        title=ft.Text("导入数据恢复", color=colors["text"]),
                        subtitle=ft.Text("警告：覆盖现有记录", size=12, color="red"),
                        on_click=lambda _: import_picker.pick_files(allow_multiple=False, allowed_extensions=["db"]),
                        content_padding=0,
                        dense=True # 【修改】：紧凑
                    )
                ]),

                # 关于
                setting_card("关于", [
                    ft.ListTile(
                        leading=ft.Icon("info", color=colors["icon"]),
                        title=ft.Text("关于 Omnis", size=16, color=colors["text"]),
                        trailing=ft.Icon("chevron_right", color=colors["icon"]),
                        on_click=show_about,
                        content_padding=0,
                        dense=True # 【修改】：紧凑
                    )
                ]),
                
                ft.Container(content=ft.Text("My Omnis v1.0.0 Beta", color=colors["sub_text"], size=12), alignment=ft.alignment.center, padding=20)
            ],
            scroll="hidden", expand=True, alignment="center", horizontal_alignment="center", spacing=15
        )
    
    # 导航逻辑
    def on_nav_change(e):
        # 1. 重新获取当前颜色的配置 (因为可能刚切换了暗黑模式)
        current_colors = get_app_colors()
        
        # 2. 【核心修复】：强制更新导航栏颜色
        page.navigation_bar.bgcolor = current_colors["card"]
        # page.navigation_bar.update() # page.update() 会涵盖它，所以这里不用单独写
        
        idx = e.control.selected_index
        page.clean()
        
        if idx == 0: page.add(get_log_view())
        elif idx == 1: page.add(get_tools_view())
        elif idx == 2: page.add(get_settings_view())
        
        page.update()

    # 0.22.1 导航栏写法
    # 获取初始颜色
    init_colors = get_app_colors()
    
    page.navigation_bar = ft.NavigationBar(
        selected_index=1,
        on_change=on_nav_change,
        # 【核心修复】：这里使用动态颜色变量，而不是死板的 "white"
        bgcolor=init_colors["card"], 
        # indicator_color=init_colors["orange"], # (可选) 你也可以定制指示器颜色
        destinations=[
            ft.NavigationDestination(icon="pets", label="日志"),
            ft.NavigationDestination(icon="build", label="工具"),
            ft.NavigationDestination(icon="settings", label="设置"),
        ]
    )

    page.add(get_tools_view())

if __name__ == "__main__":
    ft.app(target=main, assets_dir="icons")