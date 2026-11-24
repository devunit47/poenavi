import base64
import unittest
import zlib

import pytest

from src.utils import pob_importer
from src.utils.pob_importer import get_skill_sets_from_xml, parse_pob_xml


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding>
  <Build className="Duelist" ascendClassName="Slayer" />
  <Skills activeSkillSet="2">
    <SkillSet title="Act 1" id="1">
      <Skill label="Starter" enabled="true">
        <Gem nameSpec="Splitting Steel" skillId="SplittingSteel" gemId="Metadata/Items/Gems/SkillGemSplittingSteel" />
        <Gem nameSpec="Chance to Bleed" skillId="SupportChanceToBleed" gemId="Metadata/Items/Gems/SupportGemChanceToBleed" />
      </Skill>
    </SkillSet>
    <SkillSet title="Endgame" id="2">
      <Skill label="Final" enabled="true">
        <Gem nameSpec="Lacerate" skillId="Lacerate" gemId="Metadata/Items/Gems/SkillGemLacerate" />
      </Skill>
    </SkillSet>
  </Skills>
</PathOfBuilding>
"""


def test_decode_pob_rejects_oversized_input_before_stripping(monkeypatch):
    monkeypatch.setattr(pob_importer, "MAX_POB_CODE_LENGTH", 4)
    with pytest.raises(ValueError, match="文字数"):
        pob_importer.decode_pob_code(" " * 5)


def test_decode_pob_enforces_expanded_size_limit(monkeypatch):
    xml = SAMPLE_XML.encode()
    code = base64.urlsafe_b64encode(zlib.compress(xml)).decode().rstrip("=")
    monkeypatch.setattr(pob_importer, "MAX_DECOMPRESSED_BYTES", len(xml))
    assert pob_importer.decode_pob_code(code) == SAMPLE_XML

    monkeypatch.setattr(pob_importer, "MAX_DECOMPRESSED_BYTES", len(xml) - 1)
    with pytest.raises(ValueError, match="展開サイズ"):
        pob_importer.decode_pob_code(code)


def test_parse_pob_xml_parses_skill_sets_from_the_same_tree(monkeypatch):
    original = pob_importer.ET.fromstring
    parsed = []

    def fromstring(xml):
        parsed.append(xml)
        return original(xml)

    monkeypatch.setattr(pob_importer.ET, "fromstring", fromstring)
    assert parse_pob_xml(SAMPLE_XML)["skill_sets"][1]["active"]
    assert parsed == [SAMPLE_XML]


class PoBImporterSkillSetTest(unittest.TestCase):
    def test_get_skill_sets_from_xml_marks_active_set(self):
        skill_sets = get_skill_sets_from_xml(SAMPLE_XML)

        self.assertEqual(
            skill_sets,
            [
                {"id": "1", "title": "Act 1", "active": False, "index": 0},
                {"id": "2", "title": "Endgame", "active": True, "index": 1},
            ],
        )

    def test_parse_pob_xml_filters_selected_skill_sets(self):
        result = parse_pob_xml(SAMPLE_XML, selected_skill_set_ids=["1"])

        self.assertEqual(result["class"], "duelist")
        self.assertEqual(result["ascendancy"], "slayer")
        self.assertEqual(result["selected_skill_set_ids"], ["1"])
        self.assertEqual(result["gem_names"], ["chance to bleed", "splitting steel"])
        self.assertEqual(len(result["gem_groups"]), 1)
        self.assertEqual(result["gem_groups"][0]["skill_set_title"], "Act 1")
        self.assertTrue(result["gem_groups"][0]["gems"][1]["is_support"])

    def test_parse_pob_xml_without_filter_imports_all_skill_sets(self):
        result = parse_pob_xml(SAMPLE_XML)

        self.assertEqual(result["gem_names"], ["chance to bleed", "lacerate", "splitting steel"])
        self.assertEqual(len(result["gem_groups"]), 2)


if __name__ == "__main__":
    unittest.main()
