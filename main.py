import flet as ft

def main(page: ft.Page):
    page.add(ft.Text("如果不白屏，说明手机没问题！", size=30, color="green"))
    page.add(ft.Text("问题出在原来的代码逻辑里。", size=20))

# 【核心修改】：assets_dir 设为 None，不加载任何资源，排除干扰
if __name__ == "__main__":
    ft.app(target=main)