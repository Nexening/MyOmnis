import flet as ft
# 注意：我故意删除了 sqlite3, datetime, json, os, pathlib
# 甚至不引入它们，防止 import 阶段就崩溃

def main(page: ft.Page):
    page.title = "Flet Hello World"
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    page.add(
        ft.Column(
            [
                ft.Icon(name=ft.icons.FAVORITE, color="red", size=100),
                ft.Text("如果你能看到这个", size=30, weight="bold"),
                ft.Text("说明 Flet 引擎是好的！", size=20),
                ft.Text("死因确诊为：SQLite 兼容性问题", color="blue"),
            ],
            horizontal_alignment="center",
        )
    )

if __name__ == "__main__":
    ft.app(target=main)