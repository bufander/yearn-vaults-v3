from _pytest.warning_types import warn_explicit_for
from utils.utils import days_to_secs
from utils.constants import MAX_BPS, MAX_BPS_ACCOUNTANT, WEEK, YEAR, DAY
from ape import chain, reverts
import pytest


############ HELPERS ############
def assert_strategy_reported(
    log, strategy_address, gain, loss, current_debt, total_fees, total_refunds
):
    assert log.strategy == strategy_address
    assert log.gain == gain
    assert log.loss == loss
    assert log.current_debt == current_debt
    assert log.total_fees == total_fees
    assert log.total_refunds == total_refunds


def assert_price_per_share(vault, pps):
    assert (
        pytest.approx(vault.price_per_share() / 10 ** vault.decimals(), rel=1e-4) == pps
    )


def create_and_check_profit(
    asset,
    strategy,
    gov,
    vault,
    profit,
    total_fees=0,
    total_refunds=0,
    by_pass_fees=False,
):
    # We create a virtual profit
    initial_debt = vault.strategies(strategy).current_debt
    asset.transfer(strategy, profit, sender=gov)
    tx = vault.process_report(strategy, sender=gov)
    event = list(tx.decode_logs(vault.StrategyReported))

    assert_strategy_reported(
        event[0],
        strategy.address,
        profit,
        0,
        initial_debt + profit,
        total_fees if not by_pass_fees else event[0].total_fees,
        total_refunds,
    )
    return event[0].total_fees


def create_and_check_loss(strategy, gov, vault, loss, total_refunds=0):
    # We create a virtual profit
    initial_debt = vault.strategies(strategy).current_debt

    strategy.setLoss(gov, loss, sender=gov)
    tx = vault.process_report(strategy, sender=gov)
    event = list(tx.decode_logs(vault.StrategyReported))

    assert event[0].strategy == strategy.address
    assert event[0].gain == 0
    assert event[0].loss == loss
    assert event[0].current_debt == initial_debt - loss
    assert event[0].total_refunds == total_refunds

    return event[0].total_fees


def check_vault_totals(vault, total_debt, total_idle, total_assets, total_supply):
    assert vault.total_idle() == total_idle
    assert vault.total_debt() == total_debt
    assert vault.totalAssets() == total_assets
    assert pytest.approx(vault.totalSupply(), rel=1e-4) == total_supply


def increase_time_and_check_profit_buffer(
    chain, vault, secs=days_to_secs(10), expected_buffer=0
):
    # We increase time after profit has been released and update strategy debt to 0
    chain.pending_timestamp = chain.pending_timestamp + secs - 1
    chain.mine(timestamp=chain.pending_timestamp)
    assert pytest.approx(vault.balanceOf(vault), rel=1e-4) == expected_buffer


############ TESTS ############


def test_gain_no_fees_no_refunds_no_existing_buffer(
    asset, fish_amount, fish, initial_set_up, gov, add_debt_to_strategy
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10

    vault, strategy, _ = initial_set_up(asset, gov, amount, fish)
    create_and_check_profit(asset, strategy, gov, vault, first_profit)

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit,
    )

    increase_time_and_check_profit_buffer(chain, vault)

    assert_price_per_share(vault, 2.0)

    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert_price_per_share(vault, 2.0)
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount + first_profit,
        total_assets=amount + first_profit,
        total_supply=amount,
    )

    # User redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )

    assert asset.balanceOf(vault) == 0
    assert asset.balanceOf(fish) == fish_amount + first_profit


def test_gain_no_fees_with_refunds_accountant_not_enough_shares(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_flexible_accountant,
    set_fees_for_strategy,
    initial_set_up,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10

    management_fee = 0
    performance_fee = 0
    refund_ratio = 10_000

    vault, strategy, accountant = initial_set_up(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=first_profit // 10,
    )

    create_and_check_profit(
        asset, strategy, gov, vault, first_profit, 0, first_profit // 10
    )

    # Refunds are nos as much as desired, as accountant has limited shares
    assert vault.balanceOf(vault) == first_profit + first_profit // 10

    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=first_profit // 10,
        total_assets=amount + first_profit + first_profit // 10,
        total_supply=amount + first_profit + first_profit // 10,
    )


def test_gain_no_fees_with_refunds_no_buffer(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_flexible_accountant,
    set_fees_for_strategy,
    initial_set_up,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10

    management_fee = 0
    performance_fee = 0
    refund_ratio = 10_000

    vault, strategy, accountant = initial_set_up(
        asset, gov, amount, fish, management_fee, performance_fee, refund_ratio
    )
    total_refunds = first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    create_and_check_profit(asset, strategy, gov, vault, first_profit, 0, total_refunds)

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=amount,
        total_assets=2 * amount + first_profit,
        total_supply=amount + first_profit * (1 + refund_ratio / MAX_BPS_ACCOUNTANT),
    )
    assert vault.balanceOf(vault) == first_profit * (
        1 + refund_ratio / MAX_BPS_ACCOUNTANT
    )
    assert (
        vault.balanceOf(accountant)
        == amount - first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    )

    increase_time_and_check_profit_buffer(chain, vault)
    assert_price_per_share(vault, 3.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=amount,
        total_assets=2 * amount + first_profit,
        total_supply=amount,
    )

    add_debt_to_strategy(gov, strategy, vault, 0)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=2 * amount + first_profit,
        total_assets=2 * amount + first_profit,
        total_supply=amount,
    )
    assert_price_per_share(vault, 3.0)
    assert vault.strategies(strategy).current_debt == 0

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault, total_debt=0, total_idle=0, total_assets=0, total_supply=0
    )
    assert asset.balanceOf(vault) == 0

    # User ends up with the initial deposit, the profit and the refunds
    assert asset.balanceOf(fish) == fish_amount + first_profit * (
        1 + refund_ratio / MAX_BPS_ACCOUNTANT
    )

    # Accountant redeems shares
    with reverts("no shares to redeem"):
        vault.redeem(
            vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
        )


def test_gain_no_fees_with_refunds_with_buffer(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_flexible_accountant,
    set_fees_for_strategy,
    initial_set_up,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    second_profit = fish_amount // 10

    management_fee = 0
    performance_fee = 0
    refund_ratio = 10_000

    vault, strategy, accountant = initial_set_up(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=2 * amount,
    )

    total_refunds = first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    create_and_check_profit(asset, strategy, gov, vault, first_profit, 0, total_refunds)

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit,
        total_supply=3 * amount + first_profit,
    )
    assert vault.balanceOf(vault) == first_profit * (
        1 + refund_ratio / MAX_BPS_ACCOUNTANT
    )
    assert (
        vault.balanceOf(accountant)
        == 2 * amount - first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    )
    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=first_profit // 2 + total_refunds // 2,
    )

    price_per_share = vault.price_per_share() / 10 ** vault.decimals()
    assert price_per_share < 2.0
    assert (
        pytest.approx(vault.balanceOf(vault), rel=1e-3)
        == first_profit // 2 + total_refunds // 2
    )
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit,
        total_supply=2 * amount
        + first_profit // 2
        + first_profit * refund_ratio / MAX_BPS_ACCOUNTANT // 2,
    )

    create_and_check_profit(
        asset, strategy, gov, vault, second_profit, 0, total_refunds
    )

    assert_price_per_share(vault, price_per_share)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit + second_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit + second_profit,
        total_supply=2 * amount
        + first_profit // 2
        + first_profit * refund_ratio / MAX_BPS_ACCOUNTANT // 2
        + second_profit / price_per_share,
    )

    increase_time_and_check_profit_buffer(chain, vault)
    assert_price_per_share(vault, 5.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit + second_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit + second_profit,
        total_supply=amount,
    )

    add_debt_to_strategy(gov, strategy, vault, 0)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=3 * amount + first_profit + second_profit,
        total_assets=3 * amount + first_profit + second_profit,
        total_supply=amount,
    )
    assert_price_per_share(vault, 5.0)
    assert vault.strategies(strategy).current_debt == 0

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault, total_debt=0, total_idle=0, total_assets=0, total_supply=0
    )
    assert asset.balanceOf(vault) == 0

    # User ends up with the initial deposit, the profit and the refunds
    assert asset.balanceOf(fish) == fish_amount + first_profit * (
        1 + refund_ratio / MAX_BPS_ACCOUNTANT
    ) + second_profit * (1 + refund_ratio / MAX_BPS_ACCOUNTANT)

    # Accountant redeems shares
    with reverts("no shares to redeem"):
        vault.redeem(
            vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
        )


def test_gain_no_fees_no_refunds_with_buffer(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    initial_set_up,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    second_profit = fish_amount // 10

    management_fee = 0
    performance_fee = 0
    refund_ratio = 0

    vault, strategy, accountant = initial_set_up(
        asset, gov, amount, fish, management_fee, performance_fee, refund_ratio
    )
    total_refunds = first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    create_and_check_profit(asset, strategy, gov, vault, first_profit, 0, total_refunds)

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit,
    )

    assert vault.balanceOf(vault) == first_profit

    increase_time_and_check_profit_buffer(
        chain, vault, secs=WEEK // 2, expected_buffer=first_profit // 2
    )

    price_per_share = vault.totalAssets() / (amount + first_profit - first_profit // 2)
    assert_price_per_share(vault, price_per_share)

    # Create second profit
    create_and_check_profit(asset, strategy, gov, vault, second_profit, 0, 0)

    assert_price_per_share(vault, price_per_share)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit + second_profit,
        total_idle=0,
        total_assets=amount + first_profit + second_profit,
        total_supply=amount + first_profit // 2 + vault.convertToShares(second_profit),
    )

    assert pytest.approx(
        vault.balanceOf(vault), rel=1e-4
    ) == first_profit // 2 + vault.convertToShares(second_profit)

    increase_time_and_check_profit_buffer(chain, vault)
    assert_price_per_share(vault, 3.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit + second_profit,
        total_idle=0,
        total_assets=amount + first_profit + second_profit,
        total_supply=amount,
    )

    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert_price_per_share(vault, 3.0)
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount + first_profit + second_profit,
        total_assets=amount + first_profit + second_profit,
        total_supply=amount,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault, total_debt=0, total_idle=0, total_assets=0, total_supply=0
    )
    # User gets all the profits
    assert asset.balanceOf(fish) == fish_amount + first_profit + second_profit


def test_gain_fees_no_refunds_no_existing_buffer(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_accountant,
    set_fees_for_strategy,
    initial_set_up,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10

    # Using only performance_fee as its easier to measure for tests
    management_fee = 0
    performance_fee = 1_000
    refund_ratio = 0

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up(
        asset, gov, amount, fish, management_fee, performance_fee, refund_ratio
    )
    create_and_check_profit(
        asset,
        strategy,
        gov,
        vault,
        first_profit,
        first_profit * performance_fee / MAX_BPS_ACCOUNTANT,
    )

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=amount,
        total_assets=2 * amount + first_profit,
        total_supply=2 * amount + first_profit,
    )

    assert vault.balanceOf(vault) == first_profit * (
        1 - performance_fee / MAX_BPS_ACCOUNTANT
    )
    fee_shares = first_profit * (performance_fee / MAX_BPS_ACCOUNTANT)
    assert vault.balanceOf(accountant) == amount + fee_shares

    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(chain, vault)
    assert vault.price_per_share() / 10 ** vault.decimals() < 2.0
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=amount,
        total_assets=2 * amount + first_profit,
        total_supply=2 * amount + first_profit * performance_fee / MAX_BPS_ACCOUNTANT,
    )

    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=2 * amount + first_profit,
        total_assets=2 * amount + first_profit,
        total_supply=2 * amount + first_profit * performance_fee / MAX_BPS_ACCOUNTANT,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, vault.totalAssets() / vault.balanceOf(accountant))
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=vault.convertToAssets(
            amount + first_profit * performance_fee // MAX_BPS_ACCOUNTANT
        ),
        total_assets=vault.convertToAssets(
            amount + first_profit * performance_fee // MAX_BPS_ACCOUNTANT
        ),
        total_supply=amount + first_profit * performance_fee / MAX_BPS_ACCOUNTANT,
    )
    assert fish_amount < asset.balanceOf(fish)
    assert asset.balanceOf(fish) < fish_amount + first_profit

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )

    check_vault_totals(
        vault, total_debt=0, total_idle=0, total_assets=0, total_supply=0
    )
    assert asset.balanceOf(vault) == 0
    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount + first_profit
    )


def test_gain_fees_refunds_no_existing_buffer(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_flexible_accountant,
    set_fees_for_strategy,
    initial_set_up,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    # Using only performance_fee as its easier to measure for tests
    management_fee = 0
    performance_fee = 1_000
    refund_ratio = 10_000

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up(
        asset, gov, amount, fish, management_fee, performance_fee, refund_ratio
    )

    create_and_check_profit(
        asset,
        strategy,
        gov,
        vault,
        first_profit,
        total_fees=first_profit * performance_fee / MAX_BPS_ACCOUNTANT,
        total_refunds=first_profit * refund_ratio / MAX_BPS_ACCOUNTANT,
    )
    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=amount,
        total_assets=2 * amount + first_profit,
        total_supply=2 * amount + first_profit,
    )
    assert (
        vault.balanceOf(vault)
        == first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT)
        + first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    )
    fee_shares = first_profit * performance_fee / MAX_BPS_ACCOUNTANT
    assert (
        vault.balanceOf(accountant)
        == amount - first_profit * refund_ratio / MAX_BPS_ACCOUNTANT + fee_shares
    )

    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(chain, vault)
    assert_price_per_share(vault, (2 * amount + first_profit) / (amount + fee_shares))
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=amount,
        total_assets=2 * amount + first_profit,
        total_supply=amount + first_profit * performance_fee / MAX_BPS_ACCOUNTANT,
    )

    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=2 * amount + first_profit,
        total_assets=2 * amount + first_profit,
        total_supply=amount + fee_shares,
    )
    assert_price_per_share(vault, (2 * amount + first_profit) / (amount + fee_shares))

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, vault.totalAssets() / vault.balanceOf(accountant))
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=vault.convertToAssets(
            first_profit * performance_fee // MAX_BPS_ACCOUNTANT
        ),
        total_assets=vault.convertToAssets(
            first_profit * performance_fee // MAX_BPS_ACCOUNTANT
        ),
        total_supply=first_profit * performance_fee / MAX_BPS_ACCOUNTANT,
    )

    # User gets profit plus refunds minus fees
    assert fish_amount < asset.balanceOf(fish)
    assert (
        pytest.approx(asset.balanceOf(fish), abs=1)
        == fish_amount
        + first_profit * (1 + refund_ratio / MAX_BPS_ACCOUNTANT)
        - (2 * amount + first_profit)
        / (amount + fee_shares)
        * first_profit
        * performance_fee
        // MAX_BPS_ACCOUNTANT
    )

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )
    check_vault_totals(
        vault, total_debt=0, total_idle=0, total_assets=0, total_supply=0
    )
    assert asset.balanceOf(vault) == 0
    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount + first_profit
    )


def test_gain_fees_with_refunds_with_buffer(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_flexible_accountant,
    set_fees_for_strategy,
    initial_set_up,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    second_profit = fish_amount // 10

    management_fee = 0
    performance_fee = 1_000
    refund_ratio = 10_000

    vault, strategy, accountant = initial_set_up(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=2 * amount,
    )

    total_fees = first_profit * performance_fee / MAX_BPS_ACCOUNTANT
    total_refunds = first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    create_and_check_profit(
        asset, strategy, gov, vault, first_profit, total_fees, total_refunds
    )

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit,
        total_supply=3 * amount + first_profit,
    )
    assert vault.balanceOf(vault) == total_refunds + first_profit * (
        1 - performance_fee / MAX_BPS_ACCOUNTANT
    )
    assert vault.balanceOf(accountant) == 2 * amount - total_refunds + total_fees

    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2
        + total_refunds // 2,
    )

    price_per_share = vault.price_per_share() / 10 ** vault.decimals()
    assert price_per_share < 2.0
    assert (
        pytest.approx(vault.balanceOf(vault), rel=1e-3)
        == first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2
        + total_refunds // 2
    )
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit,
        total_supply=2 * amount
        + first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2
        + total_refunds // 2
        + total_fees,
    )

    total_second_fees = second_profit * performance_fee / MAX_BPS_ACCOUNTANT
    total_second_fees = total_second_fees / price_per_share
    total_second_refunds = second_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    total_second_refunds = total_second_refunds / price_per_share
    create_and_check_profit(
        asset, strategy, gov, vault, second_profit, total_fees, total_refunds
    )

    assert_price_per_share(vault, price_per_share)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit + second_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit + second_profit,
        total_supply=amount
        + 2 * amount
        - total_refunds
        + total_fees
        - total_second_refunds
        + total_second_fees
        + total_refunds // 2
        + first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2
        + total_second_refunds
        + second_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) / price_per_share,
    )

    increase_time_and_check_profit_buffer(chain, vault)

    assert vault.price_per_share() / 10 ** vault.decimals() < 5.0
    check_vault_totals(
        vault,
        total_debt=amount + first_profit + second_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit + second_profit,
        total_supply=amount + total_fees + total_second_fees,
    )

    add_debt_to_strategy(gov, strategy, vault, 0)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=3 * amount + first_profit + second_profit,
        total_assets=3 * amount + first_profit + second_profit,
        total_supply=amount + total_fees + total_second_fees,
    )
    assert vault.price_per_share() / 10 ** vault.decimals() < 5.0
    assert vault.strategies(strategy).current_debt == 0

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=vault.convertToAssets(vault.balanceOf(accountant)),
        total_assets=vault.convertToAssets(vault.balanceOf(accountant)),
        total_supply=total_fees + total_second_fees,
    )

    # User ends up with the initial deposit, the profit and the refunds
    assert asset.balanceOf(fish) < fish_amount + first_profit * (
        1 + refund_ratio / MAX_BPS_ACCOUNTANT
    ) + second_profit * (1 + refund_ratio / MAX_BPS_ACCOUNTANT)

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )
    check_vault_totals(
        vault, total_debt=0, total_idle=0, total_assets=0, total_supply=0
    )
    assert asset.balanceOf(vault) == 0
    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount + first_profit + second_profit
    )


def test_gain_fees_no_refunds_with_buffer(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_accountant,
    set_fees_for_strategy,
    initial_set_up,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    second_profit = fish_amount // 10
    # Using only performance_fee as its easier to measure for tests
    management_fee = 0
    performance_fee = 1_000
    refund_ratio = 0

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=0,
    )

    create_and_check_profit(
        asset,
        strategy,
        gov,
        vault,
        first_profit,
        first_profit * performance_fee / MAX_BPS_ACCOUNTANT,
    )

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit,
    )

    assert vault.balanceOf(vault) == first_profit * (
        1 - performance_fee / MAX_BPS_ACCOUNTANT
    )
    fee_shares = first_profit * performance_fee / MAX_BPS_ACCOUNTANT
    assert vault.balanceOf(accountant) == fee_shares

    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2,
    )
    assert vault.price_per_share() / 10 ** vault.decimals() < 2.0
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount
        + first_profit * performance_fee / MAX_BPS_ACCOUNTANT
        + first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2,
    )

    assert (
        pytest.approx(vault.balanceOf(vault), rel=1e-3)
        == first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2
    )

    price_per_share_before_2nd_profit = vault.price_per_share() / 10 ** vault.decimals()
    accountant_shares_before_2nd_profit = vault.balanceOf(accountant)
    vault_shares_before_2nd_profit = vault.balanceOf(vault)

    create_and_check_profit(
        asset,
        strategy,
        gov,
        vault,
        second_profit,
        total_fees=second_profit * performance_fee / MAX_BPS_ACCOUNTANT,
    )

    # # pps doesn't change as profit goes directly to buffer and fees are damped
    assert_price_per_share(vault, price_per_share_before_2nd_profit)

    assert (
        pytest.approx(vault.balanceOf(accountant), rel=1e-4)
        == accountant_shares_before_2nd_profit
        + second_profit
        * performance_fee
        // MAX_BPS_ACCOUNTANT
        / price_per_share_before_2nd_profit
    )

    assert (
        pytest.approx(vault.balanceOf(vault), 1e-4)
        == vault_shares_before_2nd_profit
        + second_profit
        * (1 - performance_fee / MAX_BPS_ACCOUNTANT)
        / price_per_share_before_2nd_profit
    )

    check_vault_totals(
        vault,
        total_debt=amount + first_profit + second_profit,
        total_idle=0,
        total_assets=amount + first_profit + second_profit,
        total_supply=amount
        + first_profit * performance_fee / MAX_BPS_ACCOUNTANT
        + first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2
        + second_profit / price_per_share_before_2nd_profit,
    )

    # We increase time and update strategy debt to 0
    increase_time_and_check_profit_buffer(chain, vault)

    # pps is not as big as fees lower it
    price_per_share_without_fees = 3.0
    assert (
        vault.price_per_share() / 10 ** vault.decimals() < price_per_share_without_fees
    )

    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert (
        vault.price_per_share() / 10 ** vault.decimals() < price_per_share_without_fees
    )
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount + first_profit + second_profit,
        total_assets=amount + first_profit + second_profit,
        total_supply=amount
        + first_profit * performance_fee / MAX_BPS_ACCOUNTANT
        + second_profit
        * performance_fee
        / MAX_BPS_ACCOUNTANT
        // price_per_share_before_2nd_profit,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, vault.totalAssets() / vault.balanceOf(accountant))

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=vault.convertToAssets(vault.balanceOf(accountant)),
        total_assets=vault.convertToAssets(vault.balanceOf(accountant)),
        total_supply=first_profit * performance_fee / MAX_BPS_ACCOUNTANT
        + second_profit
        * performance_fee
        / MAX_BPS_ACCOUNTANT
        // price_per_share_before_2nd_profit,
    )

    assert fish_amount < asset.balanceOf(fish)
    # Fish gets back profits
    assert asset.balanceOf(fish) > fish_amount + first_profit
    assert asset.balanceOf(fish) < fish_amount + first_profit + second_profit

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )
    check_vault_totals(
        vault, total_debt=0, total_idle=0, total_assets=0, total_supply=0
    )
    assert asset.balanceOf(vault) == 0
    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount + first_profit + second_profit
    )


def test_gain_fees_no_refunds_not_enough_buffer(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_flexible_accountant,
    set_fees_for_strategy,
    initial_set_up,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    second_profit = fish_amount // 10
    # Using only performance_fee as its easier to measure for tests
    management_fee = 0
    first_performance_fee = 1_000
    # Huge fee that profit cannot damp
    second_performance_fee = 20_000
    refund_ratio = 0

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        first_performance_fee,
        refund_ratio,
        accountant_deposit=0,
    )

    create_and_check_profit(
        asset,
        strategy,
        gov,
        vault,
        first_profit,
        first_profit * first_performance_fee / MAX_BPS_ACCOUNTANT,
    )

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit,
    )
    assert vault.balanceOf(vault) == first_profit * (
        1 - first_performance_fee / MAX_BPS_ACCOUNTANT
    )
    fee_shares = first_profit * (first_performance_fee / MAX_BPS_ACCOUNTANT)
    assert vault.balanceOf(accountant) == fee_shares

    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=first_profit
        * (1 - first_performance_fee / MAX_BPS_ACCOUNTANT)
        // 2,
    )
    assert vault.price_per_share() / 10 ** vault.decimals() < 2.0
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount
        + first_profit * first_performance_fee / MAX_BPS_ACCOUNTANT
        + first_profit * (1 - first_performance_fee / MAX_BPS_ACCOUNTANT) // 2,
    )

    assert (
        pytest.approx(vault.balanceOf(vault), rel=1e-3)
        == first_profit * (1 - first_performance_fee / MAX_BPS_ACCOUNTANT) // 2
    )

    price_per_share_before_2nd_profit = vault.price_per_share() / 10 ** vault.decimals()
    accountant_shares_before_2nd_profit = vault.balanceOf(accountant)

    # Increase fees to create a huge fee
    set_fees_for_strategy(
        gov,
        strategy,
        accountant,
        management_fee,
        second_performance_fee,
        refund_ratio=0,
    )
    assert accountant.fees(strategy).performance_fee == second_performance_fee

    create_and_check_profit(
        asset,
        strategy,
        gov,
        vault,
        second_profit,
        total_fees=second_profit * second_performance_fee / MAX_BPS_ACCOUNTANT,
    )

    # pps changes as profit goes directly to buffer and fees are damped
    assert (
        vault.price_per_share() / 10 ** vault.decimals()
        < price_per_share_before_2nd_profit
    )
    assert (
        pytest.approx(vault.convertToAssets(vault.balanceOf(accountant)), rel=1e-4)
        == vault.convertToAssets(accountant_shares_before_2nd_profit)
        + second_profit * second_performance_fee // MAX_BPS_ACCOUNTANT
    )

    assert vault.balanceOf(vault) == 0

    check_vault_totals(
        vault,
        total_debt=amount + first_profit + second_profit,
        total_idle=0,
        total_assets=amount + first_profit + second_profit,
        total_supply=amount
        + accountant_shares_before_2nd_profit
        + second_profit
        * second_performance_fee
        / MAX_BPS_ACCOUNTANT
        / vault.price_per_share()
        * 1e18,
    )

    # We update strategy debt to 0
    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert vault.price_per_share() / 10 ** vault.decimals() < 1.0

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount + first_profit + second_profit,
        total_assets=amount + first_profit + second_profit,
        total_supply=amount
        + first_profit * first_performance_fee / MAX_BPS_ACCOUNTANT
        + second_profit
        * second_performance_fee
        / MAX_BPS_ACCOUNTANT
        / vault.price_per_share()
        * 1e18,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=vault.convertToAssets(vault.balanceOf(accountant)),
        total_assets=vault.convertToAssets(vault.balanceOf(accountant)),
        total_supply=first_profit * first_performance_fee / MAX_BPS_ACCOUNTANT
        + second_profit
        * second_performance_fee
        / MAX_BPS_ACCOUNTANT
        / vault.price_per_share()
        * 1e18,
    )

    assert asset.balanceOf(fish) < fish_amount

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )
    check_vault_totals(
        vault, total_debt=0, total_idle=0, total_assets=0, total_supply=0
    )
    assert asset.balanceOf(vault) == 0
    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount + first_profit + second_profit
    )
    assert asset.balanceOf(accountant) - amount > 5 * second_profit


def test_loss_no_fees_no_refunds_no_existing_buffer(
    create_vault,
    asset,
    fish_amount,
    create_lossy_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_loss = fish_amount // 20

    management_fee = 0
    performance_fee = 0
    refund_ratio = 0

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up_lossy(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=0,
    )
    create_and_check_loss(
        strategy,
        gov,
        vault,
        first_loss,
        first_loss * performance_fee / MAX_BPS_ACCOUNTANT,
    )

    assert_price_per_share(vault, 0.5)
    assert vault.balanceOf(vault) == 0

    check_vault_totals(
        vault,
        total_debt=amount - first_loss,
        total_idle=0,
        total_assets=amount - first_loss,
        total_supply=amount,
    )

    # Update strategy debt to 0
    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert_price_per_share(vault, 0.5)
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount - first_loss,
        total_assets=amount - first_loss,
        total_supply=amount,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )

    assert asset.balanceOf(fish) == fish_amount - first_loss


def test_loss_fees_no_refunds_no_existing_buffer(
    create_vault,
    asset,
    fish_amount,
    create_lossy_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_accountant,
    set_fees_for_strategy,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_loss = fish_amount // 20

    management_fee = 10_000
    performance_fee = 0
    refund_ratio = 0

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up_lossy(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=0,
    )

    total_fees = create_and_check_loss(strategy, gov, vault, first_loss)

    assert vault.price_per_share() / 10 ** vault.decimals() < 0.5
    assert vault.balanceOf(vault) == 0

    check_vault_totals(
        vault,
        total_debt=amount - first_loss,
        total_idle=0,
        total_assets=amount - first_loss,
        total_supply=amount + total_fees,
    )

    # Update strategy debt to 0
    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert vault.price_per_share() / 10 ** vault.decimals() < 0.5
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount - first_loss,
        total_assets=amount - first_loss,
        total_supply=amount - total_fees,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert vault.price_per_share() / 10 ** vault.decimals() != 0
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=total_fees,
        total_assets=total_fees,
        total_supply=vault.convertToShares(total_fees),
    )
    assert asset.balanceOf(fish) < fish_amount - first_loss

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )

    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount - first_loss
    )


def test_loss_no_fees_refunds_no_existing_buffer(
    create_vault,
    asset,
    fish_amount,
    create_lossy_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_flexible_accountant,
    set_fees_for_strategy,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_loss = fish_amount // 10

    management_fee = 0
    performance_fee = 0
    refund_ratio = 10_000  # 100%

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up_lossy(
        asset, gov, amount, fish, management_fee, performance_fee, refund_ratio
    )
    create_and_check_loss(
        strategy,
        gov,
        vault,
        first_loss,
        total_refunds=first_loss * refund_ratio / MAX_BPS_ACCOUNTANT,
    )

    assert_price_per_share(vault, 1.0)
    assert vault.balanceOf(vault) == 0

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount,
        total_assets=amount,
        total_supply=amount,
    )

    assert vault.balanceOf(accountant) == 0

    # Update strategy debt to 0
    with reverts("new debt equals current debt"):
        add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount,
        total_assets=amount,
        total_supply=amount,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )
    assert asset.balanceOf(fish) == fish_amount


def test_loss_no_fees_with_refunds_with_buffer(
    create_vault,
    asset,
    fish_amount,
    create_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_flexible_accountant,
    set_fees_for_strategy,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    first_loss = fish_amount // 10

    management_fee = 0
    performance_fee = 0
    refund_ratio = 10_000

    vault, strategy, accountant = initial_set_up_lossy(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=2 * amount,
    )

    total_refunds = first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    create_and_check_profit(asset, strategy, gov, vault, first_profit, 0, total_refunds)

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit,
        total_supply=2 * amount
        + first_profit * (1 + refund_ratio / MAX_BPS_ACCOUNTANT),
    )
    assert vault.balanceOf(vault) == first_profit * (
        1 + refund_ratio / MAX_BPS_ACCOUNTANT
    )
    assert (
        vault.balanceOf(accountant)
        == 2 * amount - first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    )
    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=first_profit // 2 + total_refunds // 2,
    )

    price_per_share = vault.price_per_share() / 10 ** vault.decimals()
    assert price_per_share < 2.0
    assert (
        pytest.approx(vault.balanceOf(vault), rel=1e-3)
        == first_profit // 2 + total_refunds // 2
    )
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit,
        total_supply=2 * amount
        + first_profit // 2
        + first_profit * refund_ratio / MAX_BPS_ACCOUNTANT // 2,
    )

    create_and_check_loss(strategy, gov, vault, first_loss, total_refunds)

    assert_price_per_share(vault, price_per_share)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit - first_loss,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit - first_loss,
        total_supply=2 * amount
        + first_profit // 2
        + first_profit * refund_ratio / MAX_BPS_ACCOUNTANT // 2
        - first_loss / price_per_share,
    )

    increase_time_and_check_profit_buffer(chain, vault)
    assert_price_per_share(vault, 3.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit - first_loss,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit - first_loss,
        total_supply=amount,
    )

    add_debt_to_strategy(gov, strategy, vault, 0)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=3 * amount + first_profit - first_loss,
        total_assets=3 * amount + first_profit - first_loss,
        total_supply=amount,
    )
    assert_price_per_share(vault, 3.0)
    assert vault.strategies(strategy).current_debt == 0

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault, total_debt=0, total_idle=0, total_assets=0, total_supply=0
    )
    assert asset.balanceOf(vault) == 0

    # User ends up with the initial deposit, the profit and the refunds
    assert (
        asset.balanceOf(fish)
        == fish_amount
        + first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
        + first_loss * refund_ratio / MAX_BPS_ACCOUNTANT
    )

    # Accountant redeems shares
    with reverts("no shares to redeem"):
        vault.redeem(
            vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
        )


def test_loss_no_fees_no_refunds_with_buffer(
    create_vault,
    asset,
    fish_amount,
    create_lossy_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    first_loss = fish_amount // 50

    management_fee = 0
    performance_fee = 0
    refund_ratio = 0

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up_lossy(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=0,
    )
    create_and_check_profit(
        asset,
        strategy,
        gov,
        vault,
        first_profit,
        first_profit * performance_fee / MAX_BPS_ACCOUNTANT,
    )

    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit,
    )

    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2,
    )

    assert vault.price_per_share() / 10 ** vault.decimals() < 2.0
    price_per_share = vault.price_per_share() / 10 ** vault.decimals()

    assert pytest.approx(vault.balanceOf(vault), rel=1e-3) == first_profit // 2

    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount
        + first_profit * performance_fee / MAX_BPS_ACCOUNTANT
        + first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2,
    )

    # We create a virtual loss that doesn't change pps as its taken care by profit buffer
    create_and_check_loss(
        strategy,
        gov,
        vault,
        first_loss,
        first_loss * performance_fee / MAX_BPS_ACCOUNTANT,
    )
    assert_price_per_share(vault, price_per_share)
    assert pytest.approx(
        vault.balanceOf(vault), rel=1e-3
    ) == first_profit // 2 - vault.convertToShares(first_loss)

    check_vault_totals(
        vault,
        total_debt=amount + first_profit - first_loss,
        total_idle=0,
        total_assets=amount + first_profit - first_loss,
        total_supply=amount
        + first_profit
        - first_profit // 2
        - first_loss / price_per_share,
    )

    # We increase time and update strategy debt to 0
    increase_time_and_check_profit_buffer(chain, vault)

    assert_price_per_share(vault, (amount + first_profit - first_loss) / amount)

    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert_price_per_share(vault, (amount + first_profit - first_loss) / amount)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount + first_profit - first_loss,
        total_assets=amount + first_profit - first_loss,
        total_supply=amount,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )

    assert asset.balanceOf(fish) == fish_amount + first_profit - first_loss
    assert asset.balanceOf(fish) > fish_amount


def test_loss_fees_no_refunds_with_buffer(
    create_vault,
    asset,
    fish_amount,
    create_lossy_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_accountant,
    set_fees_for_strategy,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    first_loss = fish_amount // 50

    management_fee = 500
    performance_fee = 0
    refund_ratio = 0

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up_lossy(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=0,
    )
    total_profit_fees = create_and_check_profit(
        asset, strategy, gov, vault, first_profit, total_fees=0, by_pass_fees=True
    )

    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit,
    )
    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=first_profit * (1 - performance_fee / MAX_BPS_ACCOUNTANT) // 2,
    )

    assert vault.price_per_share() / 10 ** vault.decimals() < 2.0
    price_per_share = vault.totalAssets() / (amount + first_profit - first_profit // 2)

    assert pytest.approx(vault.balanceOf(vault), rel=1e-3) == first_profit // 2

    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit // 2,
    )

    # We create a virtual loss that doesn't change pps as its taken care by profit buffer
    total_loss_fees = create_and_check_loss(
        strategy,
        gov,
        vault,
        first_loss,
        first_loss * performance_fee / MAX_BPS_ACCOUNTANT,
    )
    total_loss_fees = total_loss_fees / price_per_share
    assert total_loss_fees > 0
    # pps is not affected by fees
    assert (
        pytest.approx(price_per_share, rel=1e-3)
        == vault.price_per_share() / 10 ** vault.decimals()
    )
    assert vault.balanceOf(vault) < first_profit // 2

    assert vault.totalAssets() == amount + first_profit - first_loss
    assert vault.totalSupply() > amount
    assert (
        vault.totalSupply() < amount + first_profit / 2
    )  # Because we have burned shares

    # We increase time and update strategy debt to 0
    increase_time_and_check_profit_buffer(chain, vault)

    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0

    # pps is slightly lower due to fees
    assert (
        vault.price_per_share() / 10 ** vault.decimals()
        < (amount + first_profit - first_loss) / amount
    )

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount + first_profit - first_loss,
        total_assets=amount + first_profit - first_loss,
        total_supply=amount + total_profit_fees + total_loss_fees,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=vault.convertToAssets(vault.balanceOf(accountant)),
        total_assets=vault.convertToAssets(vault.balanceOf(accountant)),
        total_supply=total_loss_fees + total_profit_fees,
    )
    assert vault.total_debt() == 0
    assert vault.totalSupply() == vault.balanceOf(accountant)
    assert asset.balanceOf(vault) == vault.convertToAssets(vault.balanceOf(accountant))

    assert asset.balanceOf(fish) < fish_amount + first_profit - first_loss
    assert asset.balanceOf(fish) > fish_amount

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )

    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount + first_profit - first_loss
    )


def test_loss_no_fees_no_refunds_with_not_enough_buffer(
    create_vault,
    asset,
    fish_amount,
    create_lossy_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 20
    first_loss = fish_amount // 10

    management_fee = 0
    performance_fee = 0
    refund_ratio = 0

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up_lossy(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=0,
    )

    create_and_check_profit(asset, strategy, gov, vault, first_profit)
    assert_price_per_share(vault, 1.0)
    assert vault.balanceOf(vault) == first_profit

    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit,
    )

    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=first_profit // 2,
    )

    assert vault.price_per_share() / 10 ** vault.decimals() < 2.0
    assert pytest.approx(vault.balanceOf(vault), rel=1e-3) == first_profit // 2

    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit // 2,
    )

    # We create a virtual loss
    create_and_check_loss(
        strategy,
        gov,
        vault,
        first_loss,
        0,
    )
    assert_price_per_share(vault, (amount + first_profit - first_loss) / amount)
    assert vault.balanceOf(vault) == 0

    check_vault_totals(
        vault,
        total_debt=amount + first_profit - first_loss,
        total_idle=0,
        total_assets=amount + first_profit - first_loss,
        total_supply=amount,
    )

    # We increase time and update strategy debt to 0
    increase_time_and_check_profit_buffer(chain, vault)

    assert_price_per_share(vault, (amount + first_profit - first_loss) / amount)

    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert_price_per_share(vault, (amount + first_profit - first_loss) / amount)
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount + first_profit - first_loss,
        total_assets=amount + first_profit - first_loss,
        total_supply=amount,
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )

    assert asset.balanceOf(fish) == fish_amount + first_profit - first_loss
    assert asset.balanceOf(fish) < fish_amount


def test_loss_fees_no_refunds_with_not_enough_buffer(
    create_vault,
    asset,
    fish_amount,
    create_lossy_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_accountant,
    set_fees_for_strategy,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 20
    first_loss = fish_amount // 10

    management_fee = 500
    performance_fee = 0
    refund_ratio = 0

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up_lossy(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=0,
    )

    total_profit_fees = create_and_check_profit(
        asset, strategy, gov, vault, first_profit, 0, by_pass_fees=True
    )

    assert_price_per_share(vault, 1.0)
    assert vault.balanceOf(vault) == first_profit - total_profit_fees

    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit,
    )

    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=first_profit // 2,
    )

    price_per_share = vault.price_per_share() / 10 ** vault.decimals()
    assert vault.price_per_share() / 10 ** vault.decimals() <= price_per_share
    assert pytest.approx(vault.balanceOf(vault), rel=1e-3) == first_profit // 2

    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=0,
        total_assets=amount + first_profit,
        total_supply=amount + first_profit // 2,
    )

    # We create a virtual loss
    total_loss_fees = create_and_check_loss(
        strategy,
        gov,
        vault,
        first_loss,
        0,
    )

    assert (
        vault.price_per_share() / 10 ** vault.decimals()
        < (amount + first_profit - first_loss) / amount
    )

    assert vault.balanceOf(vault) == 0
    assert total_loss_fees > 0

    check_vault_totals(
        vault,
        total_debt=amount + first_profit - first_loss,
        total_idle=0,
        total_assets=amount + first_profit - first_loss,
        total_supply=amount + vault.balanceOf(accountant),
    )

    assert pytest.approx(
        vault.price_per_share() / 10 ** vault.decimals(), rel=1e-3
    ) == (amount + first_profit - first_loss) / (
        amount + total_loss_fees / price_per_share + total_profit_fees
    )
    price_per_share = vault.price_per_share() / 10 ** vault.decimals()

    # We increase time and update strategy debt to 0
    increase_time_and_check_profit_buffer(chain, vault)

    assert vault.balanceOf(vault) == 0
    assert_price_per_share(vault, price_per_share)

    add_debt_to_strategy(gov, strategy, vault, 0)

    assert vault.strategies(strategy).current_debt == 0
    assert_price_per_share(vault, price_per_share)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount + first_profit - first_loss,
        total_assets=amount + first_profit - first_loss,
        total_supply=amount + vault.balanceOf(accountant),
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=vault.convertToAssets(vault.balanceOf(accountant)),
        total_assets=vault.convertToAssets(vault.balanceOf(accountant)),
        total_supply=vault.balanceOf(accountant),
    )

    assert asset.balanceOf(fish) < fish_amount
    assert asset.balanceOf(fish) < fish_amount + first_profit - first_loss

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )

    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount + first_profit - first_loss
    )


def test_loss_fees_refunds(
    create_vault,
    asset,
    fish_amount,
    create_lossy_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_accountant,
    set_fees_for_strategy,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_loss = fish_amount // 10

    management_fee = 500
    performance_fee = 0
    refund_ratio = 10_000  # Losses are covered 100%

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up_lossy(
        asset, gov, amount, fish, management_fee, performance_fee, refund_ratio
    )
    total_loss_fees = create_and_check_loss(
        strategy,
        gov,
        vault,
        first_loss,
        total_refunds=first_loss * refund_ratio / MAX_BPS_ACCOUNTANT,
    )

    assert total_loss_fees > 0
    assert vault.balanceOf(vault) == 0

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=amount,
        total_assets=amount,
        total_supply=amount + total_loss_fees,
    )

    assert_price_per_share(vault, 1.0)

    assert (
        pytest.approx(vault.convertToAssets(vault.balanceOf(accountant)), abs=1)
        == total_loss_fees
    )

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=total_loss_fees,
        total_assets=total_loss_fees,
        total_supply=vault.convertToShares(total_loss_fees),
    )

    assert pytest.approx(asset.balanceOf(fish), rel=1e-4) == fish_amount
    assert asset.balanceOf(fish) > fish_amount - first_loss

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )

    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount - first_loss
    )


def test_loss_fees_refunds_with_buffer(
    create_vault,
    asset,
    fish_amount,
    create_lossy_strategy,
    user_deposit,
    fish,
    add_strategy_to_vault,
    add_debt_to_strategy,
    gov,
    airdrop_asset,
    deploy_accountant,
    set_fees_for_strategy,
    initial_set_up_lossy,
):
    amount = fish_amount // 10
    first_profit = fish_amount // 10
    first_loss = fish_amount // 10

    management_fee = 500
    performance_fee = 0
    refund_ratio = 10_000  # Losses are covered 100%

    # Deposit assets to vault and get strategy ready
    vault, strategy, accountant = initial_set_up_lossy(
        asset,
        gov,
        amount,
        fish,
        management_fee,
        performance_fee,
        refund_ratio,
        accountant_deposit=2 * amount,
    )
    total_refunds = first_profit * refund_ratio / MAX_BPS_ACCOUNTANT
    total_fees = create_and_check_profit(
        asset, strategy, gov, vault, first_profit, 0, total_refunds, by_pass_fees=True
    )

    assert_price_per_share(vault, 1.0)
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit,
        total_supply=3 * amount + first_profit,
    )
    assert pytest.approx(vault.balanceOf(vault), 1e-4) == total_refunds + (
        first_profit - total_fees
    )
    assert vault.balanceOf(accountant) == amount + total_fees

    # We increase time after profit has been released and update strategy debt to 0
    increase_time_and_check_profit_buffer(
        chain,
        vault,
        secs=WEEK // 2,
        expected_buffer=(first_profit - total_fees) // 2 + total_refunds // 2,
    )

    price_per_share = vault.price_per_share() / 10 ** vault.decimals()
    assert price_per_share < 2.0
    assert (
        pytest.approx(vault.balanceOf(vault), rel=1e-3)
        == first_profit // 2 + total_refunds // 2
    )
    check_vault_totals(
        vault,
        total_debt=amount + first_profit,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit,
        total_supply=2 * amount
        + (first_profit - total_fees) // 2
        + total_refunds // 2
        + total_fees,
    )

    total_second_refunds = first_loss * refund_ratio / MAX_BPS_ACCOUNTANT
    total_second_fees = create_and_check_loss(
        strategy,
        gov,
        vault,
        first_loss,
        total_refunds=total_second_refunds,
    )
    total_second_fees = total_second_fees / price_per_share

    assert total_second_fees > 0

    increase_time_and_check_profit_buffer(chain, vault)

    assert vault.price_per_share() / 10 ** vault.decimals() < 3.0
    check_vault_totals(
        vault,
        total_debt=amount + first_profit - first_loss,
        total_idle=2 * amount,
        total_assets=3 * amount + first_profit - first_loss,
        total_supply=amount + total_fees + total_second_fees,
    )

    add_debt_to_strategy(gov, strategy, vault, 0)

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=3 * amount + first_profit - first_loss,
        total_assets=3 * amount + first_profit - first_loss,
        total_supply=amount + total_fees + total_second_fees,
    )
    assert vault.price_per_share() / 10 ** vault.decimals() < 3.0
    assert vault.strategies(strategy).current_debt == 0

    # Fish redeems shares
    vault.redeem(vault.balanceOf(fish), fish, fish, [], sender=fish)

    assert pytest.approx(vault.totalSupply(), 1e-4) == total_fees + total_second_fees

    assert asset.balanceOf(fish) < fish_amount + first_profit * (
        1 + refund_ratio / MAX_BPS_ACCOUNTANT
    ) + first_loss * (1 + refund_ratio / MAX_BPS_ACCOUNTANT)
    assert asset.balanceOf(fish) > fish_amount

    # Accountant redeems shares
    vault.redeem(
        vault.balanceOf(accountant), accountant, accountant, [], sender=accountant
    )

    check_vault_totals(
        vault,
        total_debt=0,
        total_idle=0,
        total_assets=0,
        total_supply=0,
    )

    assert (
        asset.balanceOf(accountant) + asset.balanceOf(fish)
        == 2 * fish_amount + first_profit - first_loss
    )
