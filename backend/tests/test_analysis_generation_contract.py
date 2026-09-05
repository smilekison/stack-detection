import pytest

import main


def test_analysis_phase_never_generates_artifacts(tmp_path, monkeypatch):
    (tmp_path / 'index.html').write_text('<h1>hello</h1>')

    def fail(*args, **kwargs):
        raise AssertionError('artifact generator was called during analysis')

    monkeypatch.setattr(main, 'dockerfile', fail)
    monkeypatch.setattr(main, 'compose', fail)
    monkeypatch.setattr(main, 'kubernetes', fail)
    monkeypatch.setattr(main, 'terraform', fail)

    result, _, _ = main.analyze_root(tmp_path, ['aws', 'gcp', 'azure'])

    assert result['generated_files'] == {}
    assert result['generation'] == {'status': 'not_requested', 'requested_artifact': None}


def test_generation_gate_returns_structured_error():
    with pytest.raises(main.HTTPException) as caught:
        main._generation_gate(
            {'deep_analysis': {'status': 'blocked', 'blockers': [{'title': 'No entrypoint'}]}},
            type('Spec', (), {'migrations': {}})(),
            'dockerfile',
        )

    assert isinstance(caught.value.detail, dict)
    assert caught.value.detail['phase'] == 'analysis_gate'
    assert caught.value.detail['requested_artifact'] == 'dockerfile'
    assert caught.value.detail['deep_analysis']['status'] == 'blocked'
