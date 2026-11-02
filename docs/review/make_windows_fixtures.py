"""生成 Photo Cleaner 的 Windows 手动测试素材（全部是合成图片，不碰真实照片）。

用法：python docs\\review\\make_windows_fixtures.py D:\\pc-test [--many 5000] [--huge]
扫描根目录是 <输出目录>\\扫描根；<输出目录>\\外部目录 用来测试指向根外的联接点。
输出目录必须是新的空目录：素材里有只读文件，重复运行时无法覆盖。
说明见 docs/review/04-windows-handoff.md 的 §4 A8 和 §5。
"""
import argparse
import os
import shutil
import stat
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


def win_long(path: Path) -> str:
    """超过 260 个字符的路径在 Windows 上要加 \\\\?\\ 前缀才能创建（未开启长路径支持时）。"""
    text = str(path.absolute())
    return "\\\\?\\" + text if os.name == "nt" else text


def picture(seed: int, size=(1200, 900)) -> Image.Image:
    img = Image.new("RGB", size, ((seed * 53) % 200 + 30, (seed * 97) % 200 + 30, (seed * 31) % 200 + 30))
    draw = ImageDraw.Draw(img)
    w, h = size
    for i in range(8):
        x, y = (seed * 37 + i * 211) % w, (seed * 59 + i * 157) % h
        r = (seed * 13 + i * 29) % (min(w, h) // 4) + min(w, h) // 12
        draw.ellipse([x - r, y - r, x + r, y + r], fill=((i * 70 + seed * 11) % 256, (i * 40) % 256, (seed * 90) % 256))
    return img


def save_pair(path: Path, img: Image.Image, copy_name: str | None = None, **options) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, **options)
    copy = path.with_name(copy_name or f"{path.stem} - 副本{path.suffix}")
    shutil.copy2(path, copy)
    return copy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--many", type=int, default=0, help="额外生成 N 张小图（N/2 组完全相同的副本），用于性能测试")
    parser.add_argument("--huge", action="store_true", help="额外生成约 2 亿像素的灰度 PNG（超过 Pillow 的解码上限）")
    args = parser.parse_args()
    root = args.out / "扫描根"

    save_pair(root / "中文路径" / "春节 2024（副本）" / "一号 照片.jpg", picture(1), quality=92)
    save_pair(root / "特殊字符" / "合影🎉 #1 & 50%.jpg", picture(2), quality=92)

    for orientation, seed in ((6, 3), (8, 4)):
        exif = Image.Exif()
        exif[274] = orientation  # 存储为横图，靠 EXIF 标记为竖拍
        save_pair(root / "竖拍" / f"orientation-{orientation}.jpg", picture(seed, (1200, 600)), exif=exif)

    cmyk_source = picture(5)
    save_pair(root / "CMYK" / "cmyk.jpg", cmyk_source.convert("CMYK"), quality=92)
    cmyk_source.save(root / "CMYK" / "同一张的RGB版本.jpg", quality=92)

    palette = picture(6, (400, 300)).convert("P", palette=Image.Palette.ADAPTIVE, colors=64)
    save_pair(root / "透明" / "palette.png", palette, transparency=0)

    # 每组默认保留排在第一的「X - 副本」，所以把只读属性设在默认会被删除的 X 上
    readonly = root / "只读" / "readonly.jpg"
    save_pair(readonly, picture(7), quality=92)
    os.chmod(readonly, stat.S_IREAD)  # 相当于 attrib +R

    save_pair(root / "被占用" / "locked.jpg", picture(8), quality=92)

    similar = picture(9)
    (root / "相似").mkdir(parents=True, exist_ok=True)
    similar.save(root / "相似" / "原图.jpg", quality=95)
    similar.resize((900, 675)).save(root / "相似" / "缩小重存.jpg", quality=70)

    for ext, fmt in ((".tif", "TIFF"), (".jfif", "JPEG"), (".gif", "GIF")):
        save_pair(root / "不支持的扩展名" / f"photo{ext}", picture(10), format=fmt)

    broken = root / "损坏" / "truncated.jpg"
    broken.parent.mkdir(parents=True, exist_ok=True)
    picture(11).save(broken, quality=92)
    broken.write_bytes(broken.read_bytes()[: broken.stat().st_size * 6 // 10])
    shutil.copy2(broken, broken.with_name("truncated - 副本.jpg"))

    # 超长路径：同一目录下 3 个完全相同的文件，完整路径分别是几十个、255 个、263 个字符
    deep = root / "超长路径"
    while len(str(deep.absolute())) < 190:
        deep = deep / ("长目录" + "x" * 40)
    os.makedirs(win_long(deep), exist_ok=True)
    short = deep / "a.jpg"
    picture(12).save(win_long(short), quality=92)
    for total in (255, 263):
        name_length = total - len(str(deep.absolute())) - 1
        target = deep / ("L" * (name_length - len(f"-{total}.jpg")) + f"-{total}.jpg")
        shutil.copy2(win_long(short), win_long(target))
        print(f"超长路径：{len(str(target.absolute()))} 个字符")

    save_pair(root / "大图" / "large-48mp.jpg", picture(13, (8000, 6000)), quality=90)
    noise = Image.frombytes("RGB", (2400, 1800), os.urandom(2400 * 1800 * 3))
    save_pair(root / "回收站容量" / "noise-6mb.jpg", noise, quality=95)  # 约 6 MB，用于回收站容量测试
    if args.huge:
        save_pair(root / "大图" / "huge-200mp.png", Image.new("L", (14200, 14200), 128))

    outside = args.out / "外部目录"
    save_pair(outside / "根外的照片.jpg", picture(14), quality=92)
    if os.name == "nt":
        junction = root / "联接点（指向根外）"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, text=True)
        print("联接点：" + ("已创建" if result.returncode == 0 else "失败 " + (result.stderr or result.stdout).strip()))
    else:
        print("联接点：跳过（只能在 Windows 上创建）")

    link_dir = root / "符号链接"
    link_dir.mkdir(parents=True, exist_ok=True)
    picture(15).save(link_dir / "a.jpg", quality=92)
    try:
        os.symlink(link_dir / "a.jpg", link_dir / "b-指向a的符号链接.jpg")
        print("符号链接：已创建")
    except OSError as error:
        print(f"符号链接：未创建（需要开发者模式或管理员）：{error}")

    if args.many:
        many = root / "大量文件"
        for i in range(args.many // 2):
            save_pair(many / f"img{i:05d}.jpg", picture(1000 + i, (64, 48)), quality=85)

    count = sum(1 for item in root.rglob("*") if item.is_file())
    print(f"完成：{root}（{count} 个文件）")


if __name__ == "__main__":
    main()
