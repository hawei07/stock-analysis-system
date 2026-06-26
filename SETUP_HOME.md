---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 3f11eb7fa23d664c4b1c1527387f20fd_1b83eb67708711f1986d525400d9a7a1
    ReservedCode1: rof8OZZI3Y7SzO99XVo18VhxgWTlTzct7At69WQw8dlagv1WKixBHi6VzD09HY+lKk8b7dcUY6UUUyvHq+2icQxWbeNeP/bb2FliIXXLD1fdNNuntO1bMS9npX/39Nc69ROHlbtEEXgYVi+ZRhq1LtQBDJSuuGZ3GCyxxyxy69eIZ95/VlOcgDUEbUU=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 3f11eb7fa23d664c4b1c1527387f20fd_1b83eb67708711f1986d525400d9a7a1
    ReservedCode2: rof8OZZI3Y7SzO99XVo18VhxgWTlTzct7At69WQw8dlagv1WKixBHi6VzD09HY+lKk8b7dcUY6UUUyvHq+2icQxWbeNeP/bb2FliIXXLD1fdNNuntO1bMS9npX/39Nc69ROHlbtEEXgYVi+ZRhq1LtQBDJSuuGZ3GCyxxyxy69eIZ95/VlOcgDUEbUU=
---

# 家里电脑部署指南

> 适用于从 GitHub clone 后在新电脑上搭建开发环境。

---

## 第一步：克隆仓库

```bash
cd D:\
git clone https://github.com/hawei07/stock-analysis-system.git
```

## 第二步：安装 Python 依赖

```bash
pip install -r D:\stock-analysis-system\requirements.txt
```

## 第三步：安装 MySQL 并初始化数据库

### 3.1 下载 MySQL 8.4

前往 [MySQL Community Server 8.4](https://dev.mysql.com/downloads/mysql/8.4.html)，选择 **Windows (x86, 64-bit), ZIP Archive** 下载，解压到任意目录（以下以 `D:\mysql` 为例，可根据实际路径调整）。

### 3.2 初始化数据目录

```bash
D:\mysql\bin\mysqld.exe --initialize-insecure --datadir=D:\mysql\data --console
```

`--initialize-insecure` 表示创建无密码的 root 用户，方便后续设置。

### 3.3 启动 MySQL

```bash
D:\mysql\bin\mysqld.exe --datadir=D:\mysql\data
```

此窗口保持运行，不要关闭。后续操作新开一个终端执行。

### 3.4 设置 root 密码

新开终端，先无密码登录：

```bash
D:\mysql\bin\mysql.exe -u root
```

进入 MySQL 后执行：

```sql
ALTER USER 'root'@'localhost' IDENTIFIED BY 'root';
FLUSH PRIVILEGES;
EXIT;
```

设置后密码为 `root`，与项目 `config.py` 中的配置一致。

### 3.5 创建数据库并导入数据

```bash
D:\mysql\bin\mysql.exe -u root -proot -e "CREATE DATABASE IF NOT EXISTS stock_analysis DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;"
D:\mysql\bin\mysql.exe -u root -proot stock_analysis < D:\stock-analysis-system\stock_analysis.sql
```

## 第四步：启动项目

```bash
cd D:\stock-analysis-system
python app.py
```

浏览器打开 `http://127.0.0.1:5002` 即可看到股票列表。

---

## 每次开机后启动

### 启动 MySQL

```bash
D:\mysql\bin\mysqld.exe --datadir=D:\mysql\data
```

### 启动 Flask

```bash
cd D:\stock-analysis-system
python app.py
```

访问 `http://127.0.0.1:5002`

---

## 同步代码

日常开发前拉取最新代码：

```bash
cd D:\stock-analysis-system
git pull origin main
```

开发完成后提交并推送：

```bash
git add -A
git commit -m "feat: xxx"
git push origin main
```

两台电脑之间切换开发时，记得先 `git pull` 同步，再开始写代码。
*（内容由AI生成，仅供参考）*
