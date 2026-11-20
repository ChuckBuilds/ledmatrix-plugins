#!/usr/bin/env python3
"""A stock the core's icon set lacks gets its logo downloaded, once.

Regression: VOO showed no logo, and the journal logged

    Logo not found for VOO at assets/stocks/ticker_icons/VOO.png

every couple of hours. The core ships ~5,600 ticker icons but no ETFs (VOO,
SPY, QQQ, VTI, IVV, DIA all missing), and the plugin only ever looked there.
Now update() downloads a missing stock logo once into the plugin's
assets/logos/, from the source stock-news uses, and the renderer falls back
to it.

Run: python plugins/ledmatrix-stocks/test_missing_logo_download.py
Exit 0 pass, 1 fail, 2 skip.
"""
import logging
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
try:
    import data_fetcher as df  # noqa: E402
except ImportError as exc:
    print(f"SKIP: {exc}")
    sys.exit(2)

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))
    return passed


def fetcher(responses):
    f = object.__new__(df.StockDataFetcher)
    f.logger = logging.getLogger("test-stocks")
    f.timeout = 5
    f._logo_failed = set()
    f.session = SimpleNamespace(
        get=mock.Mock(side_effect=lambda url, timeout: responses[url.rsplit("/", 1)[1][:-4]]))
    return f


def run(tmp):
    cache = Path(tmp) / "logos"
    bundled = Path(tmp) / "assets/stocks/ticker_icons"
    bundled.mkdir(parents=True)
    (bundled / "INTC.png").write_bytes(PNG)
    ok = SimpleNamespace(status_code=200, content=PNG)
    missing = SimpleNamespace(status_code=404, content=b"not found")
    f = fetcher({"VOO": ok, "ZZZZQ": missing})
    with mock.patch.object(df, "LOGO_CACHE_DIR", cache):
        saved = f.download_missing_logos(["INTC", "VOO", "ZZZZQ", "../x"])
        asked = [c.args[0].rsplit("/", 1)[1] for c in f.session.get.call_args_list]
        check("a bundled icon is not downloaded", "INTC.png" not in asked, asked)
        check("an unsafe symbol is never a filename or URL", not any(".." in a for a in asked), asked)
        check("a missing logo is downloaded", saved == 1 and (cache / "VOO.png").read_bytes() == PNG)
        check("no .part file is left behind", not list(cache.glob("*.part")))

        f.session.get.reset_mock()
        f.download_missing_logos(["INTC", "VOO", "ZZZZQ"])
        check("nothing is asked again: one saved, one remembered as unavailable",
              f.session.get.call_count == 0, f.session.get.call_args_list)

        try:
            import display_renderer as dr
        except ImportError as exc:  # needs the core and Pillow
            print(f"  (renderer checks skipped: {exc})")
            return
        r = object.__new__(dr.StockDisplayRenderer)
        r.display_width, r.display_height = 128, 32
        r.logger = logging.getLogger("test-stocks")
        r.logo_helper = SimpleNamespace(load_logo=mock.Mock(return_value=None))
        r._get_stock_logo("VOO")
        check("the renderer falls back to the downloaded logo",
              r.logo_helper.load_logo.call_args.args[1] == str(cache / "VOO.png"),
              r.logo_helper.load_logo.call_args)
        r._get_stock_logo("INTC")
        check("a bundled icon still wins",
              r.logo_helper.load_logo.call_args.args[1] == df.BUNDLED_ICON.format(symbol="INTC"))


def test_missing_logo_download():
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)            # the bundled icon path is relative to LEDMatrix's root
        try:
            run(tmp)
        finally:
            os.chdir(cwd)
    failed = [c for c, p in results if not p]
    assert not failed, failed


if __name__ == "__main__":
    try:
        test_missing_logo_download()
    except AssertionError:
        pass
    failed = [c for c, p in results if not p]
    print(f"\n{len(failed)} failed")
    sys.exit(1 if failed else 0)
