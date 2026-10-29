# 抖音作品批量导入得到大脑工具

## 功能
输入抖音博主主页链接 + 得到大脑知识库链接，自动批量导入所有作品链接到得到大脑。

## 安装依赖
```bash
pip install playwright
playwright install chromium
```

## 使用方法
```bash
python import_to_dedao.py "抖音博主主页链接" "得到大脑知识库链接" "博主名称"
```

## 示例
```bash
python import_to_dedao.py "https://www.douyin.com/user/MS4wLjABAAAAjnKGbRiPmA8tqEn8WAWSqr89M7HQhpxsJdXdgM6bebf2c9pxX4GRBWG9I6GmppEA" "https://www.biji.com/subject/0Gk4w350/DEFAULT" "凯圣王"
```

## 注意事项
1. 运行后会打开一个浏览器，你需要手动登录得到大脑
2. 登录后等60秒，脚本会自动开始导入
3. 如果导入失败，可以重新运行，失败的会记录在结果文件里
4. 每个作品导入大约需要10秒，500条作品大约需要1.5小时

## 常见问题
Q: 为什么找不到"添加"按钮？
A: 用 `button:has-text("添加")` 文本选择器，比 ID 更稳定

Q: 为什么有时候导入失败？
A: 页面加载慢导致，重新运行一次就行

Q: 可以导入其他博主吗？
A: 可以，只要换个博主链接和得到大脑链接就行