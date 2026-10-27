def test_ci_fails_on_a_failing_test() -> None:
    assert False, "deliberate failure to prove CI blocks a broken test (DB-05)"
