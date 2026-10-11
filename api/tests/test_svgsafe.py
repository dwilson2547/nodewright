import pytest

from nodewright import svgsafe

LUCIDE = b"""<!-- @license lucide-static - ISC -->
<svg class="lucide" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="2"><rect width="20" height="8" x="2" y="2" rx="2"/>
  <line x1="6" x2="6.01" y1="6" y2="6"/></svg>"""


def test_clean_icon_passes_and_is_rebuilt():
    out = svgsafe.clean(LUCIDE)
    assert out.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert 'viewBox="0 0 24 24"' in out and 'width="24"' not in out.split(">")[0]
    assert "<rect" in out and "license" not in out  # comments don't survive


def test_inkscape_export_style_and_metadata():
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
      xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" width="10" height="20"
      inkscape:version="1.3"><sodipodi:namedview id="nv"/><metadata><x/></metadata>
      <path d="M0 0L10 10" style="fill:#ff0000;stroke-width:2;-inkscape-stroke:none"/></svg>"""
    out = svgsafe.clean(svg)
    assert 'viewBox="0 0 10 20"' in out and 'fill="#ff0000"' in out and 'stroke-width="2"' in out
    assert "inkscape" not in out and "namedview" not in out and "metadata" not in out


@pytest.mark.parametrize("bad, why", [
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script>alert(1)</script></svg>', "<script>"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1" onload="alert(1)"/>', "'onload'"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink" viewBox="0 0 1 1">'
     b'<a x:href="javascript:alert(1)"><rect/></a></svg>', "<a>"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><foreignObject><div/></foreignObject></svg>',
     "<foreignObject>"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><use href="https://evil/x.svg#a"/></svg>',
     "only links inside"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect fill="url(https://evil/p)"/></svg>',
     "url()"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><style>rect{}</style></svg>', "<style>"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect style="behavior:url(x)"/></svg>',
     "'behavior'"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><image href="#a"/></svg>', "<image>"),
    (b'<!DOCTYPE svg [<!ENTITY a "x">]><svg xmlns="http://www.w3.org/2000/svg"/>', "DTD"),
    (b'<html/>', "root element"),
    (b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', "viewBox"),
    (b'not xml', "valid XML"),
])
def test_rejects_with_reason(bad, why):
    with pytest.raises(svgsafe.SvgRejected, match=None) as exc:
        svgsafe.clean(bad)
    assert why in str(exc.value)


def test_local_references_are_fine():
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 2 2">
      <defs><linearGradient id="g"><stop offset="0" stop-color="#000"/></linearGradient>
      <circle id="c" r="1"/></defs><rect fill="url(#g)" width="2" height="2"/><use xlink:href="#c"/></svg>"""
    out = svgsafe.clean(svg)
    assert 'fill="url(#g)"' in out and 'xlink:href="#c"' in out
