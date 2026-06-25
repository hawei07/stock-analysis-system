"""股票分析系统 - 主入口"""

import sys
import subprocess


def menu():
    print("=" * 50)
    print("        股票分析系统 v1.0")
    print("=" * 50)
    print("  1. 查看股票列表")
    print("  2. 搜索股票")
    print("  3. 添加股票")
    print("  4. 更新股票")
    print("  5. 删除股票")
    print("  6. 批量导入示例数据")
    print("  0. 退出")
    print("=" * 50)


def main():
    # 首次运行自动导入示例数据（如果表为空）
    init_if_empty()

    while True:
        menu()
        choice = input("请选择: ").strip()

        if choice == "1":
            page = input("页码(默认1): ").strip() or "1"
            market = input("市场筛选(SH/SZ/BJ, 回车跳过): ").strip()
            status = input("状态筛选(正常/ST/*ST, 回车跳过): ").strip()
            extra = []
            if market:
                extra.append(f"market={market}")
            if status:
                extra.append(f"status={status}")
            subprocess.run([sys.executable, "stock_list.py", "list", f"page={page}"] + extra, cwd=r"D:\stock-analysis-system")

        elif choice == "2":
            kw = input("搜索关键字: ").strip()
            if kw:
                subprocess.run([sys.executable, "stock_list.py", "search", kw], cwd=r"D:\stock-analysis-system")

        elif choice == "3":
            code = input("股票代码: ").strip()
            name = input("股票名称: ").strip()
            market = input("市场(SH/SZ/BJ): ").strip().upper()
            industry = input("行业(回车跳过): ").strip() or None
            list_date = input("上市日期(YYYY-MM-DD, 回车跳过): ").strip() or None
            args = ["stock_list.py", "add", code, name, market]
            if industry:
                args.append(industry)
                if list_date:
                    args.append(list_date)
            elif list_date:
                args.extend([None, list_date])
            subprocess.run([sys.executable] + args, cwd=r"D:\stock-analysis-system")

        elif choice == "4":
            code = input("要更新的股票代码: ").strip()
            print("输入要修改的字段(如 name=新名称), 直接回车结束:")
            fields = []
            while True:
                f = input("  field=value: ").strip()
                if not f:
                    break
                fields.append(f)
            if fields:
                subprocess.run([sys.executable, "stock_list.py", "update", code] + fields,
                               cwd=r"D:\stock-analysis-system")

        elif choice == "5":
            code = input("要删除的股票代码: ").strip()
            if code:
                subprocess.run([sys.executable, "stock_list.py", "delete", code], cwd=r"D:\stock-analysis-system")

        elif choice == "6":
            subprocess.run([sys.executable, "stock_list.py", "import"], cwd=r"D:\stock-analysis-system")

        elif choice == "0":
            print("再见!")
            break
        else:
            print("无效选项")

        input("\n按回车继续...")


def init_if_empty():
    """如果表为空，自动导入示例数据"""
    import sys
    sys.path.insert(0, r"D:\stock-analysis-system")
    from models import Stock
    result = Stock.get_all(page=1, page_size=1)
    if result["total"] == 0:
        print("首次运行，正在导入示例数据...")
        subprocess.run([sys.executable, "stock_list.py", "import"], cwd=r"D:\stock-analysis-system")


if __name__ == "__main__":
    main()
