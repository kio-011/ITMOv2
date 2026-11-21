#pragma once

#include <deque>
#include <string>

// Простая модель банковского счёта. Деньги хранятся в копейках.
struct Account {
    int id = 0;
    std::string owner;
    long long balance_cents = 0;
    long long overdraft_limit_cents = 0;  // допустимый уход в минус
};

class Bank {
public:
    // Указатели на счета остаются валидными, пока жив Bank:
    // std::deque не перемещает элементы при добавлении в конец.
    Account* open(const std::string& owner);
    Account* find(int id);

    // Все операции требуют положительной суммы и возвращают false при отказе.
    bool deposit(int id, long long cents);
    bool withdraw(int id, long long cents);
    bool transfer(int from, int to, long long cents);

    long long total_cents() const;
    void print_report() const;

private:
    std::deque<Account> accounts_;
    int next_id_ = 1;
};

// Записывает событие в audit.log
void log_event(const std::string& note);
