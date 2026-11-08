"""DeepSeek V4 family must be present in the catalog and routeable."""

from zyko.providers.openai_compat import DeepSeekProvider


def _catalog():
    return {m.id: m for m in DeepSeekProvider.CATALOG}


def test_v4_pro_catalog_entry():
    cat = _catalog()
    assert "deepseek-v4-pro" in cat
    m = cat["deepseek-v4-pro"]
    assert m.provider == "deepseek"
    assert m.context_window == 1_000_000
    assert m.max_output == 65_536
    assert m.input_price_per_mtok == 1.32
    assert m.output_price_per_mtok == 3.96
    assert "long-context" in m.tags


def test_v4_flash_catalog_entry():
    cat = _catalog()
    assert "deepseek-v4.1-flash-1017" in cat
    m = cat["deepseek-v4.1-flash-1017"]
    assert m.context_window == 1_000_000
    assert m.input_price_per_mtok == 0.96
    assert m.output_price_per_mtok == 1.91


def test_v4_pro_is_pricier_than_flash():
    cat = _catalog()
    pro = cat["deepseek-v4-pro"]
    flash = cat["deepseek-v4.1-flash-1017"]
    assert pro.input_price_per_mtok > flash.input_price_per_mtok
    assert pro.output_price_per_mtok > flash.output_price_per_mtok
