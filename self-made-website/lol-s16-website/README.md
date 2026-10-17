# LOL S16 观赛台

2026 英雄联盟全球总决赛（S16）粉丝自制观赛网站。

- 真实赛况：赛程、比分、入围赛 / 瑞士轮 / 淘汰赛流程图，数据来自 LoL Esports 官方接口
- 页面打开后直接请求官方接口：有比赛进行时每 30 秒刷新，平时每 2 分钟刷新；请求失败时使用内嵌的数据快照
- 可选预测：打开「预测」开关后，可以为未开赛的比赛点选胜者，或按实力随机模拟
- 直播间跳转，可添加自定义直播间

## 文件

| 路径 | 说明 |
| --- | --- |
| `index.html` | 构建好的网站，直接部署这个文件 |
| `src/page.html` | 页面源码（样式、结构、脚本） |
| `src/logos.js` | 内嵌的战队 logo |
| `src/data.js` | 赛程与比分快照（离线时使用） |
| `scripts/fetch_data.py` | 从官方接口生成 `src/data.js` |
| `scripts/build.py` | 合成 `index.html` |

## 更新

```bash
python3 scripts/fetch_data.py src/data.js   # 可选：刷新快照
python3 scripts/build.py                    # 生成 index.html
```

粉丝自制，与 Riot Games 无关。
