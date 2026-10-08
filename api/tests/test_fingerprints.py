from pocketscan_api.fingerprints import params_hash, sequence_hash


def test_sequence_hash_ignores_case_and_whitespace() -> None:
    assert sequence_hash("mkv\nLA ") == sequence_hash("MKVLA")


def test_sequence_hash_differs_for_different_sequences() -> None:
    assert sequence_hash("MKV") != sequence_hash("MKL")


def test_params_hash_ignores_key_order() -> None:
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})


def test_params_hash_changes_with_values() -> None:
    assert params_hash({"a": 1}) != params_hash({"a": 2})
