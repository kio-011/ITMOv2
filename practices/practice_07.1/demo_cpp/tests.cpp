#include <iostream>

#include "bank.h"

static int failures = 0;

#define CHECK(cond)                                                         \
    do {                                                                    \
        if (!(cond)) {                                                      \
            std::cerr << "FAIL line " << __LINE__ << ": " #cond "\n";       \
            ++failures;                                                     \
        }                                                                   \
    } while (0)

static void test_pointers_stay_valid() {
    Bank bank;
    Account* first = bank.open("a");
    for (int i = 0; i < 100; ++i) bank.open("x");
    CHECK(first->id == 1);
    CHECK(first->owner == "a");
}

static void test_rejects_bad_amounts() {
    Bank bank;
    int id = bank.open("a")->id;
    CHECK(!bank.deposit(id, 0));
    CHECK(!bank.deposit(id, -5));
    CHECK(!bank.withdraw(id, 0));
    CHECK(bank.total_cents() == 0);
}

static void test_withdraw_limits() {
    Bank bank;
    Account* a = bank.open("a");
    CHECK(a->overdraft_limit_cents == 0);
    bank.deposit(a->id, 1000);
    CHECK(bank.withdraw(a->id, 1000));   // ровно в ноль можно
    CHECK(!bank.withdraw(a->id, 1));     // глубже лимита нельзя
    CHECK(bank.set_overdraft(a->id, 500));
    CHECK(bank.withdraw(a->id, 500));    // ровно до границы овердрафта
    CHECK(!bank.withdraw(a->id, 1));
}

static void test_set_overdraft_rules() {
    Bank bank;
    int id = bank.open("a")->id;
    CHECK(!bank.set_overdraft(id, -1));      // отрицательный лимит нельзя
    CHECK(!bank.set_overdraft(999, 100));    // нет такого счёта
    CHECK(bank.set_overdraft(id, 1000));
    CHECK(bank.withdraw(id, 800));           // баланс -800
    CHECK(!bank.set_overdraft(id, 500));     // долг больше нового лимита
    CHECK(bank.set_overdraft(id, 800));      // ровно по долгу можно
}

static void test_transfer_is_atomic() {
    Bank bank;
    int a = bank.open("a")->id;
    int b = bank.open("b")->id;
    bank.deposit(a, 1000);
    CHECK(!bank.transfer(a, 999, 100));  // нет получателя: деньги не пропали
    CHECK(bank.find(a)->balance_cents == 1000);
    CHECK(!bank.transfer(a, a, 100));    // самому себе нельзя
    CHECK(!bank.transfer(a, b, 5000));   // не хватает денег
    CHECK(bank.transfer(a, b, 400));
    CHECK(bank.find(a)->balance_cents == 600);
    CHECK(bank.find(b)->balance_cents == 400);
    CHECK(bank.total_cents() == 1000);
}

int main() {
    test_pointers_stay_valid();
    test_rejects_bad_amounts();
    test_withdraw_limits();
    test_set_overdraft_rules();
    test_transfer_is_atomic();
    if (failures == 0) std::cout << "All tests passed\n";
    return failures == 0 ? 0 : 1;
}
