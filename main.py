import flet as ft
import datetime
import sqlite3
import json
import shutil
import os
import traceback
from pathlib import Path

# 1. 核心逻辑
def safe_main(page: ft.Page):
    # --- 数据库初始化 ---
    # 使用 Path.home() 确保路径正确
    db_path = str(Path.home().joinpath("tuntun.db"))
    
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_str TEXT, events TEXT
            )
        """)
        conn.commit()
    except Exception as e:
        page.add(ft.Text(f"数据库初始化失败: {e}", color="red"))
        return

    # --- 简单的 UI ---
    page.title = "My Omnis"
    page.theme_mode = "light"
    page.padding = 20
    page.scroll = "auto"

    # 简单的文本展示
    page.add(
        ft.Column([
            ft.Icon(ft.icons.CHECK_CIRCLE, color="green", size=60),
            ft.Text("恭喜！App 启动成功了！", size=24, weight="bold", color="green"),
            ft.Text(f"当前运行在: {page.platform}", size=16),
            ft.Text(f"数据库路径: {db_path}", size=14, color="grey"),
            ft.Divider(),
            ft.Text("既然能看到这个页面，说明代码逻辑没问题，\n之前黑屏是因为 assets_dir 资源路径配置错了。", size=16),
        ], horizontal_alignment="center", alignment="center")
    )
    
    # 一个简单的交互测试
    def add_log(e):
        try:
            cursor.execute("INSERT INTO logs (date_str, events) VALUES (?, ?)", 
                          (datetime.datetime.now().strftime("%H:%M"), "测试点击"))
            conn.commit()
            page.snack_bar = ft.SnackBar(ft.Text("数据库写入成功！"))
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"写入失败: {ex}"), bgcolor="red")
            page.snack_bar.open = True
            page.update()

    page.add(ft.ElevatedButton("测试数据库写入", on_click=add_log))

# 2. 外部包装 (Try-Catch 安全网)
def main(page: ft.Page):
    try:
        safe_main(page)
    except Exception as e:
        page.clean()
        page.add(ft.Text(f"崩溃信息:\n{traceback.format_exc()}", color="red"))

if __name__ == "__main__":
    # 【绝对关键修改】：移除 assets_dir，移除 view 参数
    # 彻底排除资源加载导致的黑屏风险
    ft.app(target=main)