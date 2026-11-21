#include "bank.h"

#include <algorithm>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>

namespace {

// Сумма в копейках -> "123.45" без double, чтобы не терять точность.
std::string format_rub(long long cents) {
    const bool negative = cents < 0;
    const unsigned long long abs_cents =
        negative ? 0ULL - static_cast<unsigned long long>(cents)
                 : static_cast<unsigned long long>(cents);
    std::ostringstream out;
    if (negative) out << '-';
    out << abs_cents / 100 << '.' << std::setw(2) << std::setfill('0') << abs_cents % 100;
    return out.str();
}

bool can_credit(const Account& a, long long cents) {
    return a.balance_cents <= std::numeric_limits<long long>::max() - cents;
}

bool can_debit(const Account& a, long long cents) {
    return a.balance_cents - cents >= -a.overdraft_limit_cents;
}

}  // namespace

void log_event(const std::string& note) {
    // Пишем напрямую в файл, без оболочки: текст события не должен исполняться.
    std::string line = note;
    std::replace(line.begin(), line.end(), '\n', ' ');
    std::ofstream log("audit.log", std::ios::app);
    if (log) log << line << '\n';
}

Account* Bank::open(const std::string& owner) {
    Account a;
    a.id = next_id_++;
    a.owner = owner;
    accounts_.push_back(a);
    log_event("opened account for " + owner);
    return &accounts_.back();
}

Account* Bank::find(int id) {
    for (auto& a : accounts_) {
        if (a.id == id) return &a;
    }
    return nullptr;
}

bool Bank::deposit(int id, long long cents) {
    if (cents <= 0) return false;
    Account* a = find(id);
    if (!a || !can_credit(*a, cents)) return false;
    a->balance_cents += cents;
    log_event("deposit " + std::to_string(cents) + " to " + std::to_string(id));
    return true;
}

bool Bank::withdraw(int id, long long cents) {
    if (cents <= 0) return false;
    Account* a = find(id);
    if (!a || !can_debit(*a, cents)) return false;
    a->balance_cents -= cents;
    log_event("withdraw " + std::to_string(cents) + " from " + std::to_string(id));
    return true;
}

bool Bank::transfer(int from, int to, long long cents) {
    if (cents <= 0 || from == to) return false;
    // Сначала проверяем обе стороны, и только потом двигаем деньги,
    // иначе при несуществующем получателе сумма бы пропала.
    Account* src = find(from);
    Account* dst = find(to);
    if (!src || !dst) return false;
    if (!can_debit(*src, cents) || !can_credit(*dst, cents)) return false;
    src->balance_cents -= cents;
    dst->balance_cents += cents;
    log_event("transfer " + std::to_string(cents) + " from " + std::to_string(from) +
              " to " + std::to_string(to));
    return true;
}

long long Bank::total_cents() const {
    long long total = 0;
    for (const auto& a : accounts_) total += a.balance_cents;
    return total;
}

void Bank::print_report() const {
    for (const auto& a : accounts_) {
        std::cout << "#" << a.id << " " << a.owner << ": "
                  << format_rub(a.balance_cents) << " RUB\n";
    }
    std::cout << "Total: " << format_rub(total_cents()) << " RUB\n";
}
