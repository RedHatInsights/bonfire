"""Reservation status queries, polling, and namespace description.

Replaces bonfire/openshift.py get_reservation(), get_all_reservations(),
wait_on_reservation(), get_console_url(), check_for_existing_reservation()
and bonfire/namespaces.py describe_namespace()
— using EphemeralK8sClient instead of ocviapy.
"""

# TODO: Implement — see EXECUTION_PLAN.md step 1.7
