"""Timed video knowledge must retain timestamps without invented PDF pages."""
import pytest
from im19.contracts import KnowledgeUnit, stable_id

def unit(locator, **overrides):
    values = dict(knowledge_id=stable_id('test-knowledge'), document_id=stable_id('test-document'), concept='Goals', category='Investasi', subcategory='Portfolio Management', knowledge_type='principle', claim='Source claim', evidence_text='Source claim', page_start=None, page_end=None, source_chunk_ids=[stable_id('chunk')], locator=locator, model_version='test', content_hash='test')
    values.update(overrides)
    return KnowledgeUnit(**values)

def test_timestamped_video_knowledge_is_supported():
    result=unit('video:seconds:10.880-17.740')
    assert result.page_start is None and result.page_end is None

@pytest.mark.parametrize('locator',['video:seconds:5-5','video:seconds:6-5','video:seconds:-1-5','video:seconds:NaN-5','video:seconds:0-inf','video:seconds:1-5; execute code'])
def test_invalid_video_timestamps_are_rejected(locator):
    with pytest.raises(ValueError):unit(locator)

def test_unpaged_sources_cannot_invent_a_page_end():
    with pytest.raises(ValueError):unit('video:seconds:1-5',page_end=1)

def test_epub_locator_remains_supported():
    assert unit('epub:spine:1:chapter.xhtml').page_start is None
