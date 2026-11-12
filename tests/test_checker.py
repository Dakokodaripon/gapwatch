from gapwatch.checker import Window, check


def test_everything_delivered_in_order():
    report = check([1, 2, 3], [1, 2, 3])
    assert report.ok
    assert report.delivery_rate == 1.0
    assert report.missing == []


def test_missing_changes_are_grouped_into_ranges():
    report = check(list(range(1, 11)), [1, 2, 6, 7, 10])
    assert report.missing == [3, 4, 5, 8, 9]
    assert report.missing_ranges == [(3, 5), (8, 9)]
    assert report.delivered == 5
    assert not report.ok


def test_duplicates_are_counted_once_per_extra_copy():
    report = check([1, 2, 3], [1, 2, 2, 2, 3])
    assert report.duplicates == {2: 3}
    assert report.to_dict()["duplicates"] == 2
    assert report.missing == []


def test_duplicates_do_not_count_as_out_of_order():
    report = check([1, 2, 3], [1, 2, 3, 2])
    assert report.out_of_order == 0


def test_out_of_order_counts_late_first_deliveries():
    report = check([1, 2, 3, 4], [1, 3, 2, 4])
    assert report.out_of_order == 1


def test_unknown_values_are_ignored():
    report = check([1, 2], [1, 99, 2])
    assert report.ok


def test_empty_run_is_ok():
    report = check([], [])
    assert report.ok
    assert report.delivery_rate == 1.0


def test_missing_changes_are_attributed_to_disconnect_windows():
    sent = [1, 2, 3, 4, 5, 6]
    sent_at = {1: 0.1, 2: 1.1, 3: 1.2, 4: 2.0, 5: 3.1, 6: 4.0}
    windows = [Window(1.0, 1.5), Window(3.0, 3.5)]
    report = check(sent, [1, 4, 6], sent_at, windows)
    assert report.missing_by_window == [2, 1]
    assert report.missing_outside_windows == 0


def test_missing_outside_windows_is_reported_separately():
    windows = [Window(1.0, 1.5)]
    report = check([1, 2], [], {1: 1.2, 2: 9.0}, windows)
    assert report.missing_by_window == [1]
    assert report.missing_outside_windows == 1


def test_report_is_inconclusive_when_cuts_did_not_happen():
    from gapwatch.cli import _format
    from gapwatch.listen_notify import RunConfig, RunResult

    result = RunResult(run_id="x", sent=[1, 2], received=[1, 2], faults_requested=3)
    result.fault_errors.append("cut at 1.00s failed: backend 42 was not terminated")
    text = _format(check([1, 2], [1, 2]), result, RunConfig(dsn=""))
    assert "inconclusive" in text
    assert "3 connection cut(s) requested, 0 happened" in text
    assert "no changes lost" not in text


def test_report_says_no_loss_only_when_all_cuts_happened():
    from gapwatch.cli import _format
    from gapwatch.listen_notify import RunConfig, RunResult

    result = RunResult(
        run_id="x", sent=[1], received=[1], windows=[Window(1.0, 2.0)], faults_requested=1
    )
    text = _format(check([1], [1], {1: 0.5}, result.windows), result, RunConfig(dsn=""))
    assert "Result: no changes lost." in text
