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


def _req(**overrides):
    return main.AnalyzeRequest(repo_url='https://github.com/example/repo', **overrides)


def test_no_existing_dockerfile_generates_as_before(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>hello</h1>')
    result, _, spec = main.analyze_root(tmp_path, ['aws'])
    filename, content, result, generation = main._generate_from_analysis(tmp_path, result, spec, 'dockerfile', _req())
    assert generation['status'] == 'generated'
    assert 'nginx' in content


def test_existing_dockerfile_without_mode_blocks_with_a_choice(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>hello</h1>')
    (tmp_path / 'Dockerfile').write_text('FROM scratch\n')
    result, _, spec = main.analyze_root(tmp_path, ['aws'])
    with pytest.raises(main.HTTPException) as caught:
        main._generate_from_analysis(tmp_path, result, spec, 'dockerfile', _req())
    assert caught.value.status_code == 409
    assert caught.value.detail['phase'] == 'existing_artifact_choice'
    assert caught.value.detail['existing_dockerfile']['content'] == 'FROM scratch\n'


def test_existing_dockerfile_mode_existing_returns_it_unchanged(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>hello</h1>')
    (tmp_path / 'Dockerfile').write_text('FROM scratch\n')
    result, _, spec = main.analyze_root(tmp_path, ['aws'])
    filename, content, result, generation = main._generate_from_analysis(tmp_path, result, spec, 'dockerfile', _req(mode='existing'))
    assert content == 'FROM scratch\n'
    assert generation['status'] == 'existing'
    assert generation['source'] == 'repository'


def test_existing_dockerfile_mode_generate_overrides_it(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>hello</h1>')
    (tmp_path / 'Dockerfile').write_text('FROM scratch\n')
    result, _, spec = main.analyze_root(tmp_path, ['aws'])
    filename, content, result, generation = main._generate_from_analysis(tmp_path, result, spec, 'dockerfile', _req(mode='generate'))
    assert generation['status'] == 'generated'
    assert 'nginx' in content
