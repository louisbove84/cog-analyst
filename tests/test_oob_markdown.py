"""OOB Markdown scraper tests (synthetic article, no large fixture needed)."""

from cog_analyst.ingestion.oob_markdown import parse_markdown

_SAMPLE = """Source URL: https://example.org/oob
Title: Sample

## 空军

### 空軍航空兵部隊

#### 歼击机部队

##### 东部战区空军

| 航空兵部队 | 驻地 | 战术编号 | 机型 | 备注 |
| --- | --- | --- | --- | --- |
| 空9旅 | 安徽芜湖市[湾里机场](/b) | 62X0X | [歼-20A](/c) | 上海基地 |
| 空95旅 | 江苏连云港市白塔埠机场 | 70X6X | 歼-11B、歼-10A/B/C/S | 上海基地 |
| 空999旅 | 北京市 | 12345 |  | 仅司令部 |

#### 无人机部队

| 航空兵部队 | 驻地 | 战术编号 | 机型 | 备注 |
| --- | --- | --- | --- | --- |
| 空151旅 | 河北省沧州市 | 攻击-1 | 中部战区空军 |  |

## 海军

### 海军航空兵部队

#### 陆基航空兵部队

| 航空兵部队 | 驻地 | 战术编号 | 机型 | 备注 |
| --- | --- | --- | --- | --- |
| 海航1师 | 山东青岛 | 8XX1X | 运-8特种机 | 北部战区空军第10轰炸机师 |

## 军用飞机编号与战斗序列对照表

| 备注 | 0 | 1 | 2 |
| --- | --- | --- | --- |
| 1 | 空9师 | 空1师 | 空2师 |
"""


def _parse(tmp_path, **kwargs):
    path = tmp_path / "oob.md"
    path.write_text(_SAMPLE, encoding="utf-8")
    return list(parse_markdown(path, **kwargs))


# TLDR: Rows with no aircraft are dropped by default; the decoder matrix is skipped.
def test_unit_set_and_table_skipping(tmp_path):
    names = [r.unit_name for r in _parse(tmp_path)]
    assert names == ["空9旅", "空95旅", "空151旅", "海航1师"]
    # 空999旅 has no aircraft -> dropped; cross-reference rows (空9师) never parsed.
    assert "空999旅" not in names
    assert "空9师" not in names


# TLDR: Heading context (service/role/theater) is attached, links/airbase cleaned.
def test_context_and_relational_fields(tmp_path):
    by_name = {r.unit_name: r for r in _parse(tmp_path)}
    nine = by_name["空9旅"]
    assert nine.service == "PLAAF"
    assert nine.role == "fighter"
    assert nine.theater_command == "Eastern"
    assert nine.airbase == "湾里机场"
    assert nine.tactical_code == "62X0X"
    assert nine.source_url == "https://example.org/oob"
    assert [a.en_base for a in nine.aircraft] == ["J-20"]


# TLDR: Multiple aircraft in one cell are split and crosswalked to Latin keys.
def test_multiple_aircraft(tmp_path):
    by_name = {r.unit_name: r for r in _parse(tmp_path)}
    assert [a.en_base for a in by_name["空95旅"].aircraft] == ["J-11", "J-10"]


# TLDR: Column-drifted UAV row is rescued by content classification, not position.
def test_drifted_columns_classified_by_content(tmp_path):
    uav = {r.unit_name: r for r in _parse(tmp_path)}["空151旅"]
    # 攻击-1 sat in the tactical-code column but is recognized as aircraft.
    assert [a.en_base for a in uav.aircraft] == ["GJ-1"]
    assert uav.tactical_code is None
    # 中部战区空军 sat in the aircraft column but is recognized as a theater.
    assert uav.theater_command == "Central"


# TLDR: A division name in remarks is kept as text, never as a fake aircraft.
def test_division_name_not_treated_as_aircraft(tmp_path):
    naval = {r.unit_name: r for r in _parse(tmp_path)}["海航1师"]
    assert naval.service == "PLANAF"
    assert naval.role == "land_based"
    assert [a.en_base for a in naval.aircraft] == ["Y-8"]
    assert "第10轰炸机师" in (naval.remarks or "")
    assert naval.theater_command == "Northern"


# TLDR: keep_empty (require_aircraft=False) retains staff/HQ rows with no aircraft.
def test_keep_empty_retains_aircraftless_rows(tmp_path):
    names = [r.unit_name for r in _parse(tmp_path, require_aircraft=False)]
    assert "空999旅" in names
