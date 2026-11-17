"""UI-14: the screenshot comparison itself. Each case is a deliberate change that must (or must not) fail a baseline."""
from PIL import Image, ImageDraw

from tests.ui import visual as V


def _page(size=(400, 300)):
    im = Image.new("RGB", size, (245, 249, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((20, 20, 380, 60), fill=(255, 255, 255), outline=(180, 200, 220))
    d.text((30, 30), "Cystic Fibrosis Review", fill=(11, 31, 58))
    return im


def test_identical_pictures_pass():
    assert V.changed_share(_page(), _page()) == 0.0


def test_a_few_stray_pixels_pass():
    a = _page()
    for x in range(10):
        a.putpixel((x, 200), (0, 0, 0))
    assert 0 < V.changed_share(a, _page()) < V.MAX_CHANGED


def test_a_faint_difference_in_colour_does_not_count():
    a = _page()
    ImageDraw.Draw(a).rectangle((0, 100, 399, 200), fill=(246, 250, 255))      # one level off the page colour: antialiasing noise
    assert V.changed_share(a, _page()) == 0.0


def test_a_moved_or_recoloured_block_fails():
    a = _page()
    ImageDraw.Draw(a).rectangle((20, 100, 380, 160), fill=(0, 102, 204))       # a solid button where there was none
    share = V.changed_share(a, _page())
    assert share > V.MAX_CHANGED and share > 0.1


def test_a_different_size_always_fails():
    assert V.changed_share(_page((400, 300)), _page((400, 320))) == 1.0


def test_compare_and_the_side_by_side_sheet(tmp_path):
    base, same, other = tmp_path / "b.png", tmp_path / "s.png", tmp_path / "o.png"
    _page().save(base); _page().save(same)
    changed = _page()
    ImageDraw.Draw(changed).rectangle((0, 0, 399, 150), fill=(200, 0, 0))
    changed.save(other)
    assert V.compare(same, base)[0] is True
    ok, share = V.compare(other, base)
    assert ok is False and share > 0.3
    sheet = tmp_path / "diff" / "o.png"
    V.save_side_by_side(other, base, sheet)
    assert sheet.exists() and Image.open(sheet).width > 3 * 400
