import ape
import pytest
from utils import actions
from utils.constants import ROLES


@pytest.fixture(autouse=True)
def set_role(vault, gov):
    vault.set_role(
        gov.address,
        ROLES.EMERGENCY_MANAGER | ROLES.STRATEGY_MANAGER | ROLES.DEBT_MANAGER,
        sender=gov,
    )


def test_shutdown(gov, panda, vault):
    with ape.reverts():
        vault.shutdown_vault(sender=panda)
    vault.shutdown_vault(sender=gov)


def test_shutdown_cant_deposit(vault, gov, asset, deposit_into_vault):
    vault.shutdown_vault(sender=gov)
    vault_balance_before = asset.balanceOf(vault)

    with ape.reverts():
        deposit_into_vault(vault, gov)

    assert vault_balance_before == asset.balanceOf(vault)
    gov_balance_before = asset.balanceOf(gov)
    vault.withdraw(sender=gov)
    assert asset.balanceOf(gov) == gov_balance_before + vault_balance_before
    assert asset.balanceOf(vault) == 0


def test_strategy_return_funds(vault, strategy, asset, gov):
    vault_balance = asset.balanceOf(vault)
    assert vault_balance != 0
    actions.add_debt_to_strategy(gov, strategy, vault, vault_balance)
    assert asset.balanceOf(strategy) == vault_balance
    assert asset.balanceOf(vault) == 0
    vault.shutdown_vault(sender=gov)
    vault.updateDebt(strategy.address, sender=gov)
    assert asset.balanceOf(strategy) == 0
    assert asset.balanceOf(vault) == vault_balance
