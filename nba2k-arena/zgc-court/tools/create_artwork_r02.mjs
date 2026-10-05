/** R02 hand-redrawn ground study. No reference photo is projected as a texture.
 * The arrays below are deliberately editable vector paths; 100 SVG units = 1 m.
 * Photo-visible features and inferred parts are recorded in artwork/R02_NOTES.txt.
 */
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WHITE = '#efeee4', BLACK = '#343632', YELLOW = '#d6b352';
const chunks = [];
const out = x => chunks.push(x);
const group = (id, label, extra = '') => out(`<g id="${id}" inkscape:groupmode="layer" inkscape:label="${label}" ${extra}>`);
const end = () => out('</g>');
const p = (d, fill=WHITE, extra='') => out(`<path d="${d}" fill="${fill}" ${extra}/>`);
const line = (d, w=5, color=WHITE, extra='') => p(d,'none',`stroke="${color}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" ${extra}`);
const ellipse = (x,y,rx,ry,fill=WHITE,extra='') => out(`<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}" fill="${fill}" ${extra}/>`);
const xf = x => out(`<g transform="${x}">`);
let seed=280926; const rand=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
out(`<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="2865.12" height="1524" viewBox="0 0 2865.12 1524">
<title>中关村大融城 — R02 editable court and garden-plaza ground</title>
<desc>One continuous source ground: source X increases left to right and image top is source Y+. Units: 100 per metre. Painted basketball end hand-redrawn from refs01/04/05/06/09/17/18. Dense border artwork is a reconstruction of visible motifs with inferred occluded portions, not an exact tracing. Grey-cream open plaza uses refs02/03/21/22/24 without a second painted basketball half. Art terminates independently of the gameplay midpoint. No centre line, centre circle, second three-point arc or second key.</desc>
<defs>
 <clipPath id="canvas"><rect width="2865.12" height="1524"/></clipPath>
 <clipPath id="painted-edge"><path d="M0 0H1413L1499 121L1471 386L1558 640L1538 864L1496 1060L1542 1279L1487 1524H0Z"/></clipPath>
 <clipPath id="plaza-only"><path d="M1413 0H2865.12V1524H1487L1542 1279L1496 1060L1538 864L1558 640L1471 386L1499 121Z"/></clipPath>
 <pattern id="aggregate" width="83" height="91" patternUnits="userSpaceOnUse">`);
for(let i=0;i<86;i++) ellipse((rand()*83).toFixed(2),(rand()*91).toFixed(2),(.14+rand()*.53).toFixed(2),(.11+rand()*.45).toFixed(2),i%3?'#fcf9ea':'#232a25',`opacity="${(.025+rand()*.055).toFixed(3)}"`);
out(`</pattern><pattern id="paving-joints" width="122" height="91" patternUnits="userSpaceOnUse">
<path d="M0 .5H122 M0 45.5H122 M0 0V45.5 M61 45.5V91" fill="none" stroke="#91978e" stroke-width=".62" opacity=".37"/>
</pattern></defs>`);

group('continuous-plaza-ground','连续暖灰石质底层 · refs02/03/21/22/24');
out('<rect width="2865.12" height="1524" fill="#c1c2b7"/>');
// Broad shallow colour changes follow garden pathways; these are surface colour,
// never raised geometry on the playable face.
p('M1410 0H2865.12V332C2610 434 2482 608 2293 856C2171 1012 2096 1320 2154 1524H1410Z','#b1b4ab');
p('M1590 0H2734C2558 81 2500 188 2393 328C2272 486 2118 568 1953 658C1734 777 1647 975 1712 1211C1739 1323 1803 1431 1855 1524H1487L1542 1279L1496 1060L1538 864L1558 640L1471 386L1499 121Z','#c8c8bd');
p('M2680 0H2865.12V249C2703 302 2641 352 2582 420C2482 534 2432 668 2337 828C2246 981 2186 1196 2198 1363C2201 1427 2211 1488 2223 1524H2118C2084 1294 2168 1011 2253 854C2398 589 2477 404 2638 225C2684 157 2701 83 2680 0Z','#dedcd0');
// Surface joints and warm inlay squares are confined to paving colour, and do
// not imply a second painted court or rigid grid across the artwork.
out('<g clip-path="url(#plaza-only)">');
out('<rect x="1420" width="1445.12" height="1524" fill="url(#paving-joints)"/>');
for(const [x,y,s] of [[1789,117,18],[2015,252,19],[2434,94,21],[2749,173,18],[1680,494,19],[2052,540,17],[2729,716,18],[2630,991,20],[1816,992,18],[2009,1127,19],[2331,1379,20],[2790,1436,18],[2609,1182,16],[1921,765,17]])out(`<rect x="${x}" y="${y}" width="${s}" height="${s}" fill="#939e96" opacity=".34"/>`);
line('M2680 0C2701 83 2684 157 2638 225C2477 404 2398 589 2253 854C2168 1011 2084 1294 2118 1524',1.35,'#aaa99d');
line('M2865 249C2703 302 2641 352 2582 420C2482 534 2432 668 2337 828C2246 981 2186 1196 2198 1363C2201 1427 2211 1488 2223 1524',1.05,'#eeede3');
end(); end();

group('painted-black-ground','不随中点硬裁的涂装边缘 · 黑色底漆');
p('M0 0H1413L1499 121L1471 386L1558 640L1538 864L1496 1060L1542 1279L1487 1524H0Z',BLACK);
end();

group('perimeter-brush-strokes','大幅黑白笔触边界 · refs05/17/18', 'clip-path="url(#painted-edge)"');
// The visible paint border is broad, angular and unequally spaced. These long
// wedges wrap the yellow shoulder; they are not a thin regulation boundary.
p('M0 0H1362L1434 40L1373 108L998 96L611 158L271 132L0 169Z');
p('M0 1524H1455L1441 1466L1320 1432L1008 1434L633 1355L224 1390L0 1346Z');
p('M1150 0L1322 0L1540 369L1490 405L1316 201L1293 105Z');
p('M1410 300L1533 475L1558 729L1496 676L1467 521L1440 477Z');
p('M1515 926L1551 1047L1486 1261L1465 1298L1493 1117L1482 1000Z');
p('M1308 1357L1494 1146L1528 1334L1456 1524H1384L1437 1300Z');
for(const d of [
 'M30 0H81L219 135L174 149Z','M158 0H187L300 128L273 141Z',
 'M283 0H333L479 136L431 150Z','M481 0H524L638 151L588 157Z',
 'M620 0H659L780 129L731 143Z','M826 0H856L939 104L896 114Z',
 'M987 0H1050L1181 108L1110 113Z','M1105 0L1264 0L1364 130L1284 86L1312 137Z',
 'M0 1476L65 1410L112 1381L103 1424L188 1524H148Z',
 'M228 1524L284 1383L309 1411L278 1524Z','M403 1524L502 1378L541 1375L461 1524Z',
 'M614 1524L693 1368L738 1383L670 1524Z','M811 1524L890 1403L923 1415L863 1524Z',
 'M1011 1524L1093 1443L1155 1443L1082 1524Z','M1167 1524L1261 1417L1276 1446L1231 1524Z'
])p(d,BLACK);
// Long tapered swipes sit across both dark and light borders.
p('M890 141L1150 65L1081 109L1250 84L1034 152Z');
p('M1016 1380L1261 1455L1176 1442L1302 1509L1035 1423Z');
p('M1362 167L1450 297L1396 248L1483 419L1343 246Z');
end();

group('gold-play-zone','宽黄弧与黑A油漆区 · refs01/04/09/18');
// The yellow end is intentionally an artwork shape. Its edge differs from the
// white regulation arc, and is not cut at the court midpoint.
p('M0 160C193 145 275 154 429 182C616 229 773 346 887 512C1008 690 1034 835 946 1018C856 1202 694 1338 446 1382C299 1409 168 1383 0 1394Z',YELLOW);
p('M0 509L597 517L595 1009L0 1018Z',BLACK);
// Paint has tiny local colour variation, the fine aggregate is a separate layer.
p('M41 189C312 162 613 236 751 399C655 301 440 237 249 218C173 211 81 222 41 231Z','#dec06a','opacity=".16"');
end();

group('one-end-white-court-lines','照片可见单端球线 · 圆弧保持精确', 'fill="none"');
line('M0 93.98H431 A721.36 721.36 0 0 1 431 1430.02H0',5.08,'#efead3','opacity=".8"');
line('M581.66 579.12A182.88 182.88 0 0 1 581.66 944.88',4.1,'#ede9d5','opacity=".62"');
// The lane rectangle is painted as a black block; photos do not justify adding
// extra side/centre markings that were absent in the references.
end();

group('atelier-a-badge','黑色油漆区中的A · refs01/04/09');
xf('translate(304 762) rotate(90)');
line('M-97-111C-113-105-124-86-126-67L-124 63C-123 92-104 110-78 116L70 115C96 111 114 96 120 75L124-62C123-83 111-104 95-113',11.5);
line('M-74-116L72-116',10.5);
p('M-74 83L-22-83H22L75 83H38L24 41H-24L-37 83Z M-15 11H15L0-45Z',WHITE,'fill-rule="evenodd"');
end();end();

group('large-net-drawing','大幅篮网线稿 · ref06 · 遮挡段推定','clip-path="url(#painted-edge)"');
// A tall, off-axis net overlaps two angular ribbons and occupies a different
// scale to the shoe and ball. Unequal strand widths echo painted brushwork.
xf('translate(1168 270) rotate(-22)');
line('M-190-131C-81-188 125-188 223-126C277-91 270-39 214-9C119 43-70 44-181-5C-247-34-250-96-190-131Z',11);
line('M-196-103C-86-153 110-150 220-99C255-83 259-68 245-52',5);
line('M-209-15C-173 54-144 126-115 207C-69 244 25 259 107 236C151 154 190 73 238-17',10);
line('M-184-99C-176-8-143 84-107 180C-53 218 32 228 113 207',7);
line('M-110-148C-109-55-90 30-50 134L34 246',8);
line('M-13-163C-2-49 7 64 61 167L98 236',7);
line('M87-160C109-65 125 27 148 145',8);
line('M183-126C146-31 78 67-7 147L-97 218',8);
line('M245-64C167 13 97 81 25 133L-79 189',7);
line('M143-145C71-38-27 61-136 137',7);
line('M43-165C-28-89-103-13-182 68',8);
line('M-63-157C-106-98-153-42-210-6',6);
line('M-206-20C-106 61 69 83 204 46 M-162 89C-49 141 70 159 151 144 M-127 181C-38 222 45 230 117 210',5);
// Uneven outline and speed cuts avoid a repeated icon silhouette.
line('M-231-121L-268-191L-235-181 M237-148L279-212 M-113 237L-131 270L-40 283',4.5);
p('M-225-147L-291-207L-266-149L-316-170L-257-99Z');
p('M242 24L293-2L260 43L305 33L238 82Z');
end();end();

group('white-contour-illustration','大幅白色轮廓涂鸦 · ref05 · 类别和遮挡段未确认','clip-path="url(#painted-edge)"');
xf('translate(1244 634) rotate(29)');
// Keep the photo's bulbous white contour and curved cut-back marks; the object
// category is not asserted. In particular there is no invented sneaker lacing.
p('M-269-64L-232-102L-202-113L-174-100L-161-119L-134-108L-115-117L-89-93C-26-84 20-52 67-54C104-58 125-101 160-91C194-91 201-48 192-9C190 3 202 17 221 27C249 46 248 87 218 104C202 114 187 126 169 135C137 148 106 143 68 132C34 118 17 100-7 101C-84 105-166 85-211 62L-255 42L-280 9Z');
p('M-267-49C-250-61-233-69-225-88C-246-59-240-16-222 9L-202 28C-230 19-251 4-267-13Z',BLACK);
p('M-207-101C-223-52-210-8-181 31C-197-14-191-65-179-100Z',BLACK);
p('M-167-99C-183-59-175-7-145 25C-164-22-154-67-148-95Z',BLACK);
p('M-128-100C-147-58-125-5-90 39C-108-3-115-48-105-91Z',BLACK);
p('M-86-84C-98-49-80-12-47 27C-65-16-64-42-52-71Z',BLACK);
p('M-38-66C-47-27-20 28 7 46C-11 12-17-22-12-53Z',BLACK);
p('M135-75C161-41 157-8 137 20C159 3 182-31 168-61Z',BLACK);
p('M165-52C185-16 155 26 146 48C152 67 173 72 186 85C180 64 165 55 164 44C198 4 195-22 178-45Z',BLACK);
line('M-267 57C-200 98-103 118-24 114C18 109 43 145 99 154C156 169 183 147 223 124',5);
line('M-238 68C-162 106-86 121-17 118 M129 144C157 154 184 136 199 126',3.3);
end();end();

group('basketball-and-swipe','白篮球与断开的速度笔触 · refs05/06','clip-path="url(#painted-edge)"');
xf('translate(1183 1118) rotate(-16)');
p('M-164-179C-58-209 44-206 130-159C214-110 256-22 220 82C190 171 79 215-42 187C-127 168-191 129-228 70L-202 63C-161 118-105 147-29 161C67 181 166 147 189 63C218-19 181-89 108-132C28-175-76-179-172-154Z');
// Thick sweeping seams divide irregular painted panels.
line('M-60-184C-94-53-91 63-103 169',13);
line('M80-159C11-87-11 3-12 167',12);
line('M-155-137C-113-71-23-14 207-11',11);
line('M-195 26C-101 15 16 27 206 86',12);
line('M-40-187C84-70 118 57 69 175',10);
// Photograph shows white strokes extending from the ball into the dark area.
p('M-195-114L-314-163L-264-154L-335-185L-191-144Z');
p('M-206-32L-342-35L-268-14L-367-16L-214 7Z');
p('M-196 83L-325 108L-269 110L-308 125L-172 109Z');
p('M-192-98C-179-105-171-127-170-152C-151-126-149-102-142-90L-129-52C-157-75-175-87-192-98Z');
line('M-169-149L-221-166 M-227 65L-258 69',4);
end();end();

group('brush-letterforms','不规则白色书写与切角图形 · refs01/04/06','clip-path="url(#painted-edge)"');
xf('translate(1068 822) rotate(-22)');
p('M-49-111C-100-91-138-38-123-8C-100 22-61 1-29-33C-38-1-63 58-56 93C-46 127-10 140 24 122C59 104 78 71 99 37L78 44C52 74 29 95 10 93C-3 91-5 73 2 49L60-121L20-126L-18-47C-39-11-72 10-80-10C-87-29-66-71-31-89Z');
p('M75-72L62-41C91-55 106-67 111-85C119-107 108-116 96-105Z');
line('M-96 125Q-29 168 65 132',4.5);
end();
xf('translate(1279 1480) rotate(-7)');
p('M-195-115L-61-168L40-146L125-75L71-64L32-99L-11-67L-65-86L-106-38L-174-38L-208-68Z');
p('M-180-87L-146-101L-98-64L-124-43L-160-47Z M-117-118L-60-143L-26-130L-65-99Z M2-125L24-121L61-87L38-80Z',BLACK);
line('M-177-19L-122 0L-82-16L-17 19L51 1L89 16 M-137 31L-44 44L1 34',7);
end();
end();

group('spark-dots-hatching','大小不一的星芒、红色圆点与飞白 · refs04/05/06');
// These are placed into gaps between illustrations. They do not form a uniform
// row or repeat on the unpainted half.
for(const [x,y,s,r] of [[1067,520,31,-17],[1395,872,40,20],[939,1311,33,-7],[1445,244,27,11],[1390,117,17,-22],[904,261,19,9],[1365,1338,24,25],[1520,680,15,20]]){
 xf(`translate(${x} ${y}) rotate(${r}) scale(${s/35})`);
 p('M0-43C4-14 14-4 46 0C14 5 5 15 0 43C-4 15-16 4-47 0C-17-5-5-15 0-43Z');end();
}
for(const [x,y,r] of [[1003,448,9],[1093,556,12],[1431,1033,10],[920,1212,13],[1015,1395,8],[1438,1290,9],[1336,141,7],[1396,359,10],[1511,823,7],[991,943,8],[779,112,6],[1164,1498,7]])ellipse(x,y,r,r*.93,'#c34346');
for(const [x,y,rx,ry,r] of [[960,653,14,5,18],[1054,1452,13,6,-22],[1502,1130,15,5,38],[1118,407,12,4,-12],[1397,509,18,5,32],[923,1099,12,5,16]])ellipse(x,y,rx,ry,WHITE,`transform="rotate(${r} ${x} ${y})"`);
for(const d of ['M1308 384L1345 416 M1317 372L1361 408','M977 1489L994 1501 M1004 1484L1020 1496','M1491 881L1512 904 M1484 890L1497 906','M906 454L924 471 M893 466L911 483','M1432 1377L1462 1348 M1453 1388L1474 1364'])line(d,3.5);
end();

group('fine-mineral-aggregate','细粒表面 · 可编辑平铺颗粒','pointer-events="none"');
out('<rect width="2865.12" height="1524" fill="url(#aggregate)"/>');
end();
out('</svg>');
await writeFile(path.join(ROOT,'artwork/court.svg'),chunks.join('\n')+'\n','utf8');
console.log('R02 editable ground artwork written: artwork/court.svg');
