"""股票列表管理 — CLI 交互"""

import sys
from models import Stock
from tabulate import tabulate


def show_list(args):
    """显示股票列表"""
    page = int(args[0]) if len(args) > 0 else 1
    market = None
    status = None
    keyword = None

    # 简单参数解析: python stock_list.py [page] [market=SH|SZ|BJ] [status=正常|...] [keyword=xxx]
    for a in args:
        if a.startswith("market="):
            market = a.split("=", 1)[1].upper()
        elif a.startswith("status="):
            status = a.split("=", 1)[1]
        elif a.startswith("keyword=") or a.startswith("search="):
            keyword = a.split("=", 1)[1]
        elif a.startswith("page="):
            page = int(a.split("=", 1)[1])

    result = Stock.get_all(page=page, page_size=20, market=market, status=status, keyword=keyword)

    if not result["data"]:
        print("暂无股票数据")
        return

    headers = ["ID", "代码", "名称", "市场", "行业", "上市日期", "状态"]
    rows = []
    for s in result["data"]:
        rows.append([
            s["id"], s["code"], s["name"], s["market"],
            s.get("industry", "-") or "-",
            str(s.get("list_date", "-")) if s.get("list_date") else "-",
            s["status"],
        ])

    print(tabulate(rows, headers=headers, tablefmt="grid"))
    print(f"\n第 {result['page']}/{result['total_pages']} 页，共 {result['total']} 条记录")


def add_stock(args):
    """添加股票: python stock_list.py add <代码> <名称> <市场> [行业] [上市日期]"""
    if len(args) < 3:
        print("用法: add <代码> <名称> <市场(SH/SZ/BJ)> [行业] [上市日期]")
        return
    code, name, market = args[0], args[1], args[2].upper()
    if market not in ("SH", "SZ", "BJ"):
        print("市场必须是 SH(上海)、SZ(深圳) 或 BJ(北京)")
        return
    industry = args[3] if len(args) > 3 else None
    list_date = args[4] if len(args) > 4 else None

    try:
        Stock.add(code, name, market, industry, list_date)
        print(f"已添加: {code} {name}")
    except Exception as e:
        print(f"添加失败: {e}")


def update_stock(args):
    """更新股票: python stock_list.py update <代码> field=value ..."""
    if len(args) < 2:
        print("用法: update <代码> [name=xxx] [market=SH] [industry=xxx] [list_date=2024-01-01] [status=正常]")
        return
    code = args[0]
    kwargs = {}
    for a in args[1:]:
        if "=" in a:
            k, v = a.split("=", 1)
            kwargs[k] = v
    try:
        cnt = Stock.update(code, **kwargs)
        print(f"已更新 {code}，影响 {cnt} 行" if cnt else f"未找到股票 {code}")
    except Exception as e:
        print(f"更新失败: {e}")


def delete_stock(args):
    """删除股票: python stock_list.py delete <代码>"""
    if not args:
        print("用法: delete <代码>")
        return
    code = args[0]
    confirm = input(f"确认删除 {code}？(y/n): ")
    if confirm.lower() != "y":
        print("已取消")
        return
    try:
        cnt = Stock.delete(code)
        print(f"已删除 {code}" if cnt else f"未找到股票 {code}")
    except Exception as e:
        print(f"删除失败: {e}")


def search_stock(args):
    """搜索股票: python stock_list.py search <关键字>"""
    if not args:
        print("用法: search <关键字>")
        return
    keyword = args[0]
    result = Stock.get_all(keyword=keyword, page_size=50)
    if not result["data"]:
        print(f"未找到匹配 '{keyword}' 的股票")
        return
    headers = ["代码", "名称", "市场", "行业", "状态"]
    rows = [[s["code"], s["name"], s["market"], s.get("industry", "-") or "-", s["status"]]
            for s in result["data"]]
    print(tabulate(rows, headers=headers, tablefmt="grid"))
    print(f"共 {result['total']} 条匹配")


def batch_import(args):
    """批量导入示例（硬编码20只常见股票）"""
    stocks = [
        ("600519", "贵州茅台", "SH", "白酒", "2001-08-27", "正常"),
        ("000858", "五粮液", "SZ", "白酒", "1998-04-27", "正常"),
        ("601318", "中国平安", "SH", "保险", "2007-03-01", "正常"),
        ("000333", "美的集团", "SZ", "家电", "2013-09-18", "正常"),
        ("600036", "招商银行", "SH", "银行", "2002-04-09", "正常"),
        ("000651", "格力电器", "SZ", "家电", "1996-11-18", "正常"),
        ("601166", "兴业银行", "SH", "银行", "2007-02-05", "正常"),
        ("002415", "海康威视", "SZ", "安防", "2010-05-28", "正常"),
        ("600276", "恒瑞医药", "SH", "医药", "2000-10-18", "正常"),
        ("000725", "京东方A", "SZ", "面板", "2001-01-12", "正常"),
        ("601888", "中国中免", "SH", "旅游", "2009-10-15", "正常"),
        ("002594", "比亚迪", "SZ", "汽车", "2011-06-30", "正常"),
        ("600030", "中信证券", "SH", "证券", "2003-01-06", "正常"),
        ("000001", "平安银行", "SZ", "银行", "1991-04-03", "正常"),
        ("601857", "中国石油", "SH", "石油", "2007-11-05", "正常"),
        ("300750", "宁德时代", "SZ", "电池", "2018-06-11", "正常"),
        ("688981", "中芯国际", "SH", "半导体", "2020-07-16", "正常"),
        ("600900", "长江电力", "SH", "电力", "2003-11-18", "正常"),
        ("002714", "牧原股份", "SZ", "农牧", "2014-01-28", "正常"),
        ("300059", "东方财富", "SZ", "互联网金融", "2010-03-19", "正常"),
    ]
    try:
        cnt = Stock.batch_add(stocks)
        print(f"已批量导入 {cnt} 只股票")
    except Exception as e:
        print(f"导入失败: {e}")


COMMANDS = {
    "list": show_list,
    "add": add_stock,
    "update": update_stock,
    "delete": delete_stock,
    "search": search_stock,
    "import": batch_import,
}


def main():
    if len(sys.argv) < 2:
        print("股票列表管理")
        print("  list [page] [market=SH|SZ|BJ] [status=正常|ST] [keyword=xxx]  查看列表")
        print("  add <代码> <名称> <市场> [行业] [上市日期]                      添加股票")
        print("  update <代码> field=value ...                                  更新股票")
        print("  delete <代码>                                                 删除股票")
        print("  search <关键字>                                               搜索股票")
        print("  import                                                        批量导入示例数据")
        return

    cmd = sys.argv[1].lower()
    args = sys.argv[2:]

    if cmd in COMMANDS:
        COMMANDS[cmd](args)
    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
