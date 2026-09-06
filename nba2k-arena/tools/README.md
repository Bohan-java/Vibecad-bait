# 手动导出原生篮架资源（Windows）

`export_basket_resources.ps1` 供拥有本地 NBA 2K26 的用户手动运行，读取本机 `manifest` 指定的四段数据，导出供现有 Reader 缓存使用的原生篮架 buffers。无需安装 Python、建模软件或其它工具；支持 **64 位 Windows PowerShell 5.1 / PowerShell 7**，若压缩为 Oodle 则调用游戏已有的 `data\oodle\oo2core_9_win64.dll`。不复制 DLL，不启动游戏、不下载、不上传、不自动导入或推送。

**此脚本在交付前只经过 macOS 静态审阅，未在 Windows 执行，也未完成 PowerShell/C# 编译验证。** 包头/尾部按项目先前读出的 VCZ 约定处理；本次在 Mac 复核了已有已解码 floor 缓存：90,468 字节、CRC32 `bae3d241`。这不能代替 Windows / Oodle / 四条篮架资源的实际测试。脚本会逐项校验，任何不一致即停止，不把失败数据报告为成功。

在普通权限的 **64 位 PowerShell** 中切换到本目录，替换游戏路径；输出路径必须是一个尚不存在的新目录，其父目录已存在：

```powershell
.\export_basket_resources.ps1 `
  -GameRoot 'D:\steam\steamapps\common\NBA 2K26' `
  -OutputDirectory "$env:USERPROFILE\Downloads\NBA2K26-basket-export-20260906"
```

如果系统策略阻止本地脚本，请先查看其内容，并按自己的 Windows 管理要求处理；脚本不会修改执行策略或请求管理员权限。路径含空格时保留引号。再运行时使用新的输出目录和新的 PowerShell 会话。

为避免目录联接把写入位置绕回游戏目录，脚本拒绝路径中的 symlink/junction/reparse point、UNC 与网络映射盘；若 SteamLibrary 或 Downloads 使用了此类链接，请指定真实的本地物理目录。不会跟随链接寻找游戏。`manifest` 是游戏根目录下的同名文件，支持原无标题的四列 CSV，也允许第一条记录为 `name,container,offset,size`。

只对以下 **basename 做大小写不敏感的完整匹配**，不使用包含、前缀、通配或首个匹配；缺失、重复、container 路径越界、读取不足或长度不符均失败：

| 输出文件名 | 必须解码为 |
|---|---:|
| `IndexBuffer.2faa94a692eecb55.gz` | 1,340,664 字节 |
| `VertexBuffer.396eff6e2f806326.gz` | 363,992 字节 |
| `VertexBuffer.c7008f082a4e24dd.gz` | 181,996 字节 |
| `VertexBuffer.8d2e607c050161de.gz` | 1,091,976 字节 |

输入必须有已核实的 VCZ wrapper：首两字节 `1f 8b`，偏移 12–15 为 `VCZ\0`，压缩 payload 为 `[16, length-8)`，最后 8 字节是小端 CRC32 与解码长度。支持内层 zlib（另校验 Adler32）或现有 Oodle DLL；任何成功输出同时满足固定尺寸、VCZ trailer 尺寸与解码 CRC32。

成功的新目录有四个 buffers 和 `basket_resources.metadata.json`。**文件虽然保留原 `.gz` 后缀，内容已经解码，不是普通 gzip，不能再次解压。** metadata 记录 manifest 精确原名/行号/container/offset/size、原始段/payload/解码数据 SHA-256、CRC32、codec 及实际使用的 Oodle DLL SHA-256；不包含 DLL 本体。

四条资源先在内存全部校验，随后用 `CreateNew` 写到同级唯一 `.partial-…` 临时目录，最后改名为指定新目录；现有文件和目录不会被替换。若写入阶段出错，错误会给出未完成目录路径，脚本不会删除用户文件；以终端的完成消息及正式目录中的 metadata 为准。资源不会自动复制进项目、游戏或任何远端位置，后续交接由用户自行决定。
