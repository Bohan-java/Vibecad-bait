"""Publish current delivery metadata without changing watched source inputs."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def main():
    report=json.loads((ROOT/'validation/iff-current.json').read_text(encoding='utf8'))
    manifest=json.loads((ROOT/'public/manifest.json').read_text(encoding='utf8'))
    output=ROOT/'output/arena_700_int.iff'
    assert output.stat().st_size==report['output_bytes']
    assert report['archive_crc_verified'] and not report['after_d3d']['failed']
    rev=report['revision']
    half_turn=bool(report.get('half_court_orientation'))
    for filename, payload in [('ground-depth-current.json',report['ground_depth_candidate']),
                               ('shared-floor-line-override.json',report['shared_line_candidate']),
                               ('native-basket-rig-current.json',report['basket_rig']),
                               ('glass-current-audit.json',report['glass_repair']),
                               ('native-d3d-texture-validation.json',report['after_d3d']),
                               ('bench-seating-current.json',report['bench_seating'])]:
        (ROOT/'validation'/filename).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    manifest.update(iff_version=rev+' · 右侧替补席、左侧近景与远楼',game_verified_version='R11-context-defects',
        iff={'revision':rev,'file':'output/arena_700_int.iff','bytes':report['output_bytes'],
             'sha256':report['output_sha256'],'game_tested':False,'game_visibility':'pending',
             'source_version':report['source_version']},
        last_game_test={'revision':'R11','game_visibility':'gameplay_visible_context_and_bench_defects',
                       'user_result':'打球截图正常显示；替补重叠无座位，左侧空旷、可见地图边缘；Chili’s应改长方形主体。回放玻璃本轮未确认。'})
    if half_turn:
        manifest.update(iff_version=rev+' · 黄黑半场换端',
                        game_verified_version='R12-half-court-wrong-end',
                        last_game_test={'revision':'R12',
                                        'game_visibility':'half_court_uses_gray_open_end',
                                        'user_result':'用户确认街球半场选项进入灰色开放半场。本轮将整套自建场景换端，使黄黑涂装与Chili’s对应到该入口；尚待游戏确认。'})
        manifest['iff']['half_court_orientation']=report['half_court_orientation']
    if report.get('chilis_frontage'):
        manifest['iff_version']=rev+' · Chili’s 主立面细节与材质'
        manifest['latest_feedback']='用户认为模型大体可以；本轮聚焦朝场门店材质和篮板透明度、反光。'
    (ROOT/'public/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    status=f'''中关村大融城球场 · {rev}
当前唯一游戏文件：output/arena_700_int.iff
目标：Blacktop，拖入平时使用的 levels，文件名 arena_700_int.iff。
大小：{report['output_bytes']:,} 字节
SHA256：{report['output_sha256']}

本轮依据草稿新增左侧、远楼照片及既有门店照片，修正场边空间。
右侧增加一排黑色座椅，并从本地未修改原版球馆读取44个已有替补/教练/工作人员角色标记；各标记有独立位置并与椅子对应。
Blacktop是否采用这些标记、实际坐姿是否对齐，仍需一次游戏确认；没有修改人员数量、球员和教练资源。
左侧按连续帧中的门店、围栏、树木遮挡关系补低层建筑与近场细节；仅裁去明确局部范围内旧推定花境，保留其它植栽。
远处按照片角度增加简化楼群、远树及地面延伸，遮住原地图边缘；未能确认的楼名、绝对间距与高度不冒充实测。
Chili’s取消整段椭圆平面，改为长直立面、短侧面和局部小圆角；保留R11详细门店构件。
用户确认：面对球场后的主入口，喷泉露台在左侧绕过转角。
主入口保留灰紫实体招牌底板、左右字位、黑框双扇门及灰石铺地；喷泉露台使用银色竖格和独立立体字，两面分别建模。
按原图细化金属立柱、屋顶百叶、雨棚与底部支架、侧棚字标、红色编织椅、方桌拼缝及喷泉等可见结构。
门窗与露台围护采用细框、边缘结构及可视开口，保留照片可见的浅层室内；尚未模拟整片光学玻璃的反射/折射，不使用未经验证的静态透明着色器。
绝对尺度、小圆角半径与隐藏后立面仍为推定；不把照片上传日期当拍摄日期，不复制积雪、圣诞及开业临时布置。
灯具和招牌仅制作结构与日间材质，灯光效果留待后续。

延续既有球场兼容修复：
R11用户截图显示打球正常；回放黑板、近看白框的结果尚未确认，本轮沿用R10专用篮板玻璃方案。
玻璃采用原生室外球场的完整材质、Presentation 通道和资源绑定；仅凭网页透明不能证明游戏回放正常。
开放半场及周围改为中灰水泥质感，保留低对比铺地曲线与细微骨料纹理；全局灯光和曝光未改。
另一半场增加白色三分线、罚球线/半圆及三秒区边线，坐标沿用NBA原生场地尺度与篮心。
左侧长围网外补照片中的高杆投光灯，按围网和篮架高度比重建，灯头为实体结构且暂不发光；尺寸为照片推定。
自建上部框架、伸臂、瞄准框与玻璃接入同一原生运动骨骼；立柱按原生权重过渡，地脚固定。
原生篮圈位置、权重、12级LOD索引、对象身份及运动绑定保留；离线姿态核对通过，真实挂框和回放仍待游戏确认。
罚球半圆端点贴合黑区前缘，补每侧4根站位短杠。短杠位置取可读原生球场坐标，照片无法精确辨认，未冒充照片实测。
地面 A 保持约1.48:1的窄长外形，并修正朝向；黄色外边界保持半径7.239m、底角6.7056m。
增加实际玩法范围的边线和底线。三分判定最终以游戏为准。
围网大 A 改为细长槽壳、窄 A 字与上下留断口的白色实体扩散罩；白色代表灯带结构，本轮不发光。
Chili’s 在上方时，左侧围网长于右侧；长短关系有照片依据，13.28m/11.28m绝对长度仍为推定。
篮后连续黑底、两侧黑白笔触延伸至围栏；围栏外采用暖灰铺装，开放广场保留原图所示的弯曲铺地。
保留零高度地面、无相机深度偏移、原生共享线透明覆盖，避免恢复旧版标志遮挡和红线。
比赛篮圈、原生动态球网、比赛锚点、全局灯光与后处理保持既有兼容流程；灯带照明留待后续。

网页默认“游戏包预览”：从当前 IFF 解码坐标、法线、UV、索引和 DDS，不读取源 GLB 代替游戏内容。
“编辑源预览”用于查看保存后的源工程，尚未打包的改动不会冒充最终 IFF。
网页可以检查图案、模型和贴图；游戏灯光、动态网与外部地板的最终绘制次序不能完全由网页重现。
外部地板缓存缺原始顶点流，无法忠实复现这层几何，不以干净网页作为游戏叠线消失证据。
当前 {rev} 尚未游戏确认。网页可先检查外观，之后只集中做一轮游戏核对。

最新可编辑源：source/scene.blend、artwork/court.svg、artwork/paving-context.svg、textures/r03/。
内部 zgc_r03 标识和 textures/r03 是当前资源名，不是旧版交付。
保留当前工程、预览、工具和原图；旧 IFF、旧预览和临时附属文件清理。
未拍清的建筑部分及间距仍按照片推定，没有声称精确实测。
所有修改均在项目内，没有写入游戏目录。
'''
    usage=f'''中关村大融城球场 · {rev}

先看网页
双击 Start_Preview.bat，或打开 http://127.0.0.1:4173。
默认“游戏包预览”，显示从当前 IFF 读出的模型和贴图。
先绕球场查看右侧黑色替补席、左侧门店和近场树木，再转动镜头查看四周远楼与树冠是否遮住地图边缘。
用“Chili’s 主入口”“喷泉露台”“店侧通道”“露台细节”检查门店；俯视核对其矩形主体，参考照片可点击放大对照。
面对主入口，喷泉露台在左侧绕转角，两处门头的底板、字位和入口分别建模。
用“另一半场”核对灰水泥和白色简易半场线；“左侧高路灯”核对杆高、灯头及安装位置。
“俯视 · Chili’s 在上方”可核对完整两半场、左右围网与场边的衔接。
用篮架正面、侧面、背面核对玻璃与支撑；网页不模拟游戏回放专用渲染。
可拖动绕场查看，也可隐藏围网或建筑；白色灯带目前仅有结构，不发光。
切到“编辑源预览”可查看保存后的源工程；游戏包需要重新打包才更新。
网页光照与游戏不完全相同，不能验证动态网、碰撞、计分和外部地板的最终显示次序。

游戏只复制一个文件
output\\arena_700_int.iff
大小 {report['output_bytes']:,} 字节。
等网页外观确认后，再完全退出游戏，将它拖入平时使用的 levels 替换同名文件。
进入同一 Blacktop，一轮集中核对：
1. 替补与教练是否各自落在右侧座椅，是否还重叠；如异常，记录对应角色和位置。
2. 左侧建筑、近树、围栏和步道关系是否正常；转动镜头查看远楼与地图边缘。
3. 绕Chili’s转角检查矩形主体及门店细节。如有同次回放，顺便确认篮板玻璃和白框，不另开一轮测试。
不用每项细节改动都重新开游戏；不支持或假定热加载。

回滚
完全退出游戏后，用原“洛克公园”底包的副本改名 arena_700_int.iff，替换 levels 中同名文件。
不要覆盖原始底包。本工程没有自动安装任何文件。

版本保留
output 只保留当前一个 IFF。工程、当前网页预览和原图供继续修改，不用复制到游戏。
'''
    if half_turn:
        status=status.replace('本轮依据草稿新增左侧、远楼照片及既有门店照片，修正场边空间。',
            '本轮 R12.1 仅修正街球半场选错端：用户确认 R12 半场入口进入灰色开放半场。\n'
            '将整套自建球场及周边模型水平换端180°，替补和教练位置同步换端；原生比赛锚点、篮架运动、灯光与后处理保持原位。\n'
            '黄黑涂装、Chili’s、左右围栏及环境的相互关系保持不变；未修改模型顶点、贴图或原生篮球架资源。\n'
            '本轮离线检查不代表游戏确认。完全退出游戏后替换一次，选择 Blacktop 半场，核对是否进入黄黑涂装与Chili’s这一侧即可。\n\n'
            '以下为保留的 R12 场边空间与既有兼容修改：')
        usage=f'''中关村大融城球场 · {rev} · 黄黑半场换端

本轮只修正 Blacktop 半场入口对应到灰色开放场地的问题。
整套自建模型及替补位置换端，保留黄黑球场、Chili’s、左右围栏和周边的相互关系。
网页仍可打开 http://127.0.0.1:4173，默认查看当前游戏包。

游戏只复制一个文件
output\\arena_700_int.iff
大小 {report['output_bytes']:,} 字节。
1. 完全退出游戏，将这个文件拖入平时使用的 levels，替换同名文件。
2. 启动游戏并选择 Blacktop 的半场选项，确认进入黄黑涂装、篮后为 Chili’s 的半场。
本轮只需这一次集中核对；不假定支持热加载。离线检查已完成，游戏结果尚未确认。

回滚
完全退出游戏后，用原“洛克公园”底包的副本改名 arena_700_int.iff，替换 levels 中同名文件。
不要覆盖原始底包。本工程没有自动安装任何文件。

版本保留
output 只保留当前一个 IFF。工程、当前网页预览和原图供继续修改，不用复制到游戏。
R12 场边建模及此前兼容工作的详细说明保留在 PROJECT_STATUS.txt。
'''
    if report.get('chilis_frontage'):
        evidence=json.loads((ROOT/'validation/r13-chilis-photo-audit.json').read_text(encoding='utf8'))
        status=f'''中关村大融城球场 · {rev}
当前唯一游戏文件：output/arena_700_int.iff
目标：Blacktop / arena_700_int.iff，手动拖入平时使用的 levels。
大小：{report['output_bytes']:,} 字节
SHA256：{report['output_sha256']}

本轮逐张查看 {evidence['viewed_image_count']} 张相关原图，专攻 Chili’s 正对球场这一侧。
灯牌改为有厚度的红橙侧壳、亚克力字面、连续窄内沿和安装层次；所有发光强度保持零，不把照片光晕烘进贴图。
银色凹面柱、三层檐口、小金字、门框和把手使用分别控制的金属/涂层材质与细拉丝粗糙度。
灰紫门头保留克制竖纹；米色布雨棚增加织纹、卷边和底部关节；门五金、下槛与密封层次细化。
门前灰石与基座水泥保留细颗粒、分缝和轻微色差；电梯凹口仍是红褐釉砖，不混成水泥。
材质通过实际基色/粗糙度贴图及独立金属度导出；未采用尚未验证的原生切线法线贴图。
篮板 alpha 由 10/255 增至 36/255，更不透明；粗糙度由 16/255 增至 82/255，倒影与尖锐高光变柔。
粗糙度调整不等于独立降低总反射能量；未发现可证实的原生独立反射强度参数。
篮板原生几何、骨骼和回放材质通道保留；游戏回放结果不能由离线渲染证明。

保留的场景关系：长方形 Chili’s 主体，面对主入口左转角为喷泉露台；黄黑半场位于已换端的位置。
球场地板、左右围栏、替补席与角色坐标、左侧建筑、远楼树木及全局灯光保持前版。
照片无法精确证明的毫米结构与物理材质参数仍为据图近似，不声称实测复刻。

网页默认从最终 IFF 解码模型和 DDS；灯牌、门框五金、雨棚和灰石都有近景按钮。
网页和离线检查使用近似日光与材质，不等同游戏渲染或运行验证。
可编辑源为 source/scene.blend；当前纹理与原图继续保留供后续调整。
output 仅保留最新 IFF，旧导出及临时副本清理。未修改游戏目录。
'''
        usage=f'''中关村大融城球场 · {rev}

先看 http://127.0.0.1:4173/，刷新后选择“游戏包预览”。
用“灯牌近看”“门框五金”“雨棚近看”“门前灰石”检查本轮细节，并在右侧对照原图。
篮板请用“篮架正面/侧面”查看更有实体感的玻璃与柔和反光。
灯牌目前不发光，灯光效果留待后续一起调整。

游戏只复制 output\\arena_700_int.iff（{report['output_bytes']:,} 字节）。
完全退出游戏后，将它拖入平时的 levels，覆盖同名文件；不假定支持热加载。
网页外观确认后集中检查一次门店材质和篮板，勿把离线检查当成游戏已验证。
需要回滚时，退出游戏，以原“洛克公园”底包副本改名 arena_700_int.iff 替换；保留原始底包。
'''
    (ROOT/'PROJECT_STATUS.txt').write_text(status,encoding='utf8')
    (ROOT/'使用说明.txt').write_text(usage,encoding='utf8')
    test_note=('R12 用户确认半场选项进入灰色开放场地；R12.1 换端后只需一次 Blacktop 半场核对，确认黄黑球场和 Chili’s 一侧。\n'
               if half_turn else 'R12先在网页核对替补席、左侧近景、远楼遮挡和Chili’s矩形主体，再一次性进游戏确认座位标记；回放玻璃仍待确认。\n')
    if report.get('chilis_frontage'):
        test_note='R13：先网页核对主立面材质和篮板，再集中一次游戏确认。离线渲染不是游戏验证。\n'
    (ROOT/'排查与测试.txt').write_text(test_note+usage,encoding='utf8')
    print('Current delivery notes and manifest updated.')
if __name__=='__main__':main()
