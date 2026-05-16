"""
Small set of standalone, self-contained C++ bug samples for the initial
working example.  Each entry mirrors the structure of a real Defects4C record
but is compilable without any external dependencies.

Fields:
  id          – unique identifier
  description – one-line human summary of the bug
  bug_type    – category (matches Defects4C taxonomy)
  buggy_code  – complete, compilable C++ source (includes main + test)
  fixed_code  – the corrected version
  expected_output – exact stdout expected when the fixed program runs correctly
"""

SAMPLES = [
    # ── 1. Off-by-one in array loop ───────────────────────────────────────────
    {
        "id": "001_off_by_one",
        "description": "Off-by-one: loop reads one element past end of array",
        "bug_type": "buffer-overread",
        "buggy_code": r"""
#include <cstdio>
#include <cstring>

// BUG: loop goes up to and INCLUDING size (should be < size)
int sum_array(const int* arr, int size) {
    int total = 0;
    for (int i = 0; i <= size; i++) {   // off-by-one: should be i < size
        total += arr[i];
    }
    return total;
}

int main() {
    int data[] = {1, 2, 3, 4, 5};
    int result = sum_array(data, 5);
    printf("%d\n", result);
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>
#include <cstring>

int sum_array(const int* arr, int size) {
    int total = 0;
    for (int i = 0; i < size; i++) {
        total += arr[i];
    }
    return total;
}

int main() {
    int data[] = {1, 2, 3, 4, 5};
    int result = sum_array(data, 5);
    printf("%d\n", result);
    return 0;
}
""",
        "expected_output": "15\n",
    },

    # ── 2. Wrong string comparison ────────────────────────────────────────────
    {
        "id": "002_wrong_strcmp",
        "description": "Using == to compare C-strings instead of strcmp",
        "bug_type": "logic-error",
        "buggy_code": r"""
#include <cstdio>
#include <cstring>

// BUG: pointer comparison instead of strcmp
int count_word(const char** words, int n, const char* target) {
    int count = 0;
    for (int i = 0; i < n; i++) {
        if (words[i] == target)   // BUG: compares pointers, not content
            count++;
    }
    return count;
}

int main() {
    char a[] = "apple";
    char b[] = "banana";
    char c[] = "apple";
    const char* words[] = {a, b, c, b};
    // "apple" appears in a and c (different pointers, same content)
    printf("%d\n", count_word(words, 4, "apple"));
    printf("%d\n", count_word(words, 4, "banana"));
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>
#include <cstring>

int count_word(const char** words, int n, const char* target) {
    int count = 0;
    for (int i = 0; i < n; i++) {
        if (strcmp(words[i], target) == 0)   // FIX: content comparison
            count++;
    }
    return count;
}

int main() {
    char a[] = "apple";
    char b[] = "banana";
    char c[] = "apple";
    const char* words[] = {a, b, c, b};
    printf("%d\n", count_word(words, 4, "apple"));
    printf("%d\n", count_word(words, 4, "banana"));
    return 0;
}
""",
        "expected_output": "2\n2\n",
    },

    # ── 3. Wrong comparison operator ──────────────────────────────────────────
    {
        "id": "003_wrong_operator",
        "description": "Assignment used instead of equality comparison in condition",
        "bug_type": "logic-error",
        "buggy_code": r"""
#include <cstdio>

// BUG: uses = (assignment) instead of == (comparison)
int classify(int x) {
    if (x = 0) {       // BUG: should be x == 0
        return -1;
    } else if (x > 0) {
        return 1;
    } else {
        return -1;
    }
}

int main() {
    printf("%d\n", classify(5));
    printf("%d\n", classify(-3));
    printf("%d\n", classify(0));
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>

int classify(int x) {
    if (x == 0) {      // FIX: equality check
        return 0;
    } else if (x > 0) {
        return 1;
    } else {
        return -1;
    }
}

int main() {
    printf("%d\n", classify(5));
    printf("%d\n", classify(-3));
    printf("%d\n", classify(0));
    return 0;
}
""",
        "expected_output": "1\n-1\n0\n",
    },

    # ── 4. Wrong loop direction / decrement bug ───────────────────────────────
    {
        "id": "004_loop_decrement",
        "description": "Factorial returns 0 because loop variable is decremented past 1",
        "bug_type": "logic-error",
        "buggy_code": r"""
#include <cstdio>

// BUG: loop condition is i >= 0 so it multiplies by 0 at end
long long factorial(int n) {
    long long result = 1;
    for (int i = n; i >= 0; i--) {   // BUG: should be i >= 1 (or i > 0)
        result *= i;
    }
    return result;
}

int main() {
    printf("%lld\n", factorial(5));
    printf("%lld\n", factorial(3));
    printf("%lld\n", factorial(1));
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>

long long factorial(int n) {
    long long result = 1;
    for (int i = n; i >= 1; i--) {   // FIX: stop at 1, don't multiply by 0
        result *= i;
    }
    return result;
}

int main() {
    printf("%lld\n", factorial(5));
    printf("%lld\n", factorial(3));
    printf("%lld\n", factorial(1));
    return 0;
}
""",
        "expected_output": "120\n6\n1\n",
    },

    # ── 5. Wrong return value / missing base case ─────────────────────────────
    {
        "id": "005_wrong_return",
        "description": "Fibonacci returns n+1 instead of n due to wrong base case",
        "bug_type": "logic-error",
        "buggy_code": r"""
#include <cstdio>

// BUG: base case returns n+1 instead of n
int fibonacci(int n) {
    if (n <= 1) return n + 1;   // BUG: should just return n
    return fibonacci(n - 1) + fibonacci(n - 2);
}

int main() {
    for (int i = 0; i <= 6; i++) {
        printf("%d ", fibonacci(i));
    }
    printf("\n");
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>

int fibonacci(int n) {
    if (n <= 1) return n;   // FIX: correct base case
    return fibonacci(n - 1) + fibonacci(n - 2);
}

int main() {
    for (int i = 0; i <= 6; i++) {
        printf("%d ", fibonacci(i));
    }
    printf("\n");
    return 0;
}
""",
        "expected_output": "0 1 1 2 3 5 8 \n",
    },

    # ── 6. Binary search: off-by-one in loop condition ────────────────────────
    {
        "id": "006_binary_search",
        "description": "Binary search misses right-boundary and single-element targets due to left<right",
        "bug_type": "boundary-condition",
        "buggy_code": r"""
#include <cstdio>

// BUG: condition is left < right, missing the case when search range is a single slot.
int binary_search(const int* arr, int n, int target) {
    int left = 0, right = n - 1;
    while (left < right) {                     // BUG: should be left <= right
        int mid = left + (right - left) / 2;
        if (arr[mid] == target) return mid;
        if (arr[mid] < target) left = mid + 1;
        else                   right = mid - 1;
    }
    return -1;
}

int main() {
    int arr[] = {1, 3, 5, 7, 9, 11, 13};
    printf("%d\n", binary_search(arr, 7, 1));   // index 0
    printf("%d\n", binary_search(arr, 7, 7));   // index 3
    printf("%d\n", binary_search(arr, 7, 13));  // index 6 (right boundary)
    printf("%d\n", binary_search(arr, 7, 4));   // not found -> -1
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>

int binary_search(const int* arr, int n, int target) {
    int left = 0, right = n - 1;
    while (left <= right) {                    // FIX: inclusive upper bound
        int mid = left + (right - left) / 2;
        if (arr[mid] == target) return mid;
        if (arr[mid] < target) left = mid + 1;
        else                   right = mid - 1;
    }
    return -1;
}

int main() {
    int arr[] = {1, 3, 5, 7, 9, 11, 13};
    printf("%d\n", binary_search(arr, 7, 1));
    printf("%d\n", binary_search(arr, 7, 7));
    printf("%d\n", binary_search(arr, 7, 13));
    printf("%d\n", binary_search(arr, 7, 4));
    return 0;
}
""",
        "expected_output": "0\n3\n6\n-1\n",
    },

    # ── 7. Linked-list reverse: overwrites next pointer before saving ────────
    {
        "id": "007_linked_list_reverse",
        "description": "Iterative linked-list reverse loses the rest of the list by overwriting next before saving",
        "bug_type": "pointer-error",
        "buggy_code": r"""
#include <cstdio>
#include <cstdlib>

struct Node {
    int val;
    Node* next;
};

Node* make_list(const int* a, int n) {
    Node* head = nullptr;
    for (int i = n - 1; i >= 0; i--) {
        Node* node = (Node*)malloc(sizeof(Node));
        node->val = a[i];
        node->next = head;
        head = node;
    }
    return head;
}

// BUG: curr->next is overwritten with prev before we save the next pointer,
// so curr advances to nullptr after one iteration.
Node* reverse_list(Node* head) {
    Node* prev = nullptr;
    Node* curr = head;
    while (curr) {
        curr->next = prev;      // BUG: need to save curr->next BEFORE this line
        prev = curr;
        curr = curr->next;      // now always equals prev (or nullptr)
    }
    return prev;
}

void print_list(Node* head) {
    while (head) {
        printf("%d ", head->val);
        head = head->next;
    }
    printf("\n");
}

int main() {
    int a[] = {1, 2, 3, 4, 5};
    Node* list = make_list(a, 5);
    Node* reversed = reverse_list(list);
    print_list(reversed);
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>
#include <cstdlib>

struct Node {
    int val;
    Node* next;
};

Node* make_list(const int* a, int n) {
    Node* head = nullptr;
    for (int i = n - 1; i >= 0; i--) {
        Node* node = (Node*)malloc(sizeof(Node));
        node->val = a[i];
        node->next = head;
        head = node;
    }
    return head;
}

Node* reverse_list(Node* head) {
    Node* prev = nullptr;
    Node* curr = head;
    while (curr) {
        Node* next = curr->next;  // FIX: save before rewiring
        curr->next = prev;
        prev = curr;
        curr = next;
    }
    return prev;
}

void print_list(Node* head) {
    while (head) {
        printf("%d ", head->val);
        head = head->next;
    }
    printf("\n");
}

int main() {
    int a[] = {1, 2, 3, 4, 5};
    Node* list = make_list(a, 5);
    Node* reversed = reverse_list(list);
    print_list(reversed);
    return 0;
}
""",
        "expected_output": "5 4 3 2 1 \n",
    },

    # ── 8. Coin-change DP: missing base-case initialisation ──────────────────
    {
        "id": "008_coin_change_dp",
        "description": "Coin-change DP fails because dp[0] is never set to 0 (stays at sentinel value)",
        "bug_type": "initialization-error",
        "buggy_code": r"""
#include <cstdio>

// Return minimum number of coins to make `amount`, or -1 if impossible.
int coin_change(const int* coins, int n_coins, int amount) {
    int dp[1001];
    int sentinel = amount + 1;
    for (int i = 0; i <= amount; i++) dp[i] = sentinel;
    // BUG: dp[0] should be 0, the base case. Without it every transition
    //      reads a sentinel value and propagates "impossible".
    for (int i = 1; i <= amount; i++) {
        for (int j = 0; j < n_coins; j++) {
            if (coins[j] <= i && dp[i - coins[j]] + 1 < dp[i]) {
                dp[i] = dp[i - coins[j]] + 1;
            }
        }
    }
    return dp[amount] > amount ? -1 : dp[amount];
}

int main() {
    int coins1[] = {1, 2, 5};
    printf("%d\n", coin_change(coins1, 3, 11));   // 3  (5+5+1)
    printf("%d\n", coin_change(coins1, 3, 3));    // 2  (1+2)
    int coins2[] = {2};
    printf("%d\n", coin_change(coins2, 1, 3));    // -1 (impossible)
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>

int coin_change(const int* coins, int n_coins, int amount) {
    int dp[1001];
    int sentinel = amount + 1;
    for (int i = 0; i <= amount; i++) dp[i] = sentinel;
    dp[0] = 0;                          // FIX: proper base case
    for (int i = 1; i <= amount; i++) {
        for (int j = 0; j < n_coins; j++) {
            if (coins[j] <= i && dp[i - coins[j]] + 1 < dp[i]) {
                dp[i] = dp[i - coins[j]] + 1;
            }
        }
    }
    return dp[amount] > amount ? -1 : dp[amount];
}

int main() {
    int coins1[] = {1, 2, 5};
    printf("%d\n", coin_change(coins1, 3, 11));
    printf("%d\n", coin_change(coins1, 3, 3));
    int coins2[] = {2};
    printf("%d\n", coin_change(coins2, 1, 3));
    return 0;
}
""",
        "expected_output": "3\n2\n-1\n",
    },

    # ── 9. In-place matrix transpose: double-swap bug ─────────────────────────
    {
        "id": "009_matrix_transpose",
        "description": "In-place transpose visits every (i,j) pair twice, cancelling out all swaps",
        "bug_type": "loop-bound",
        "buggy_code": r"""
#include <cstdio>

// BUG: inner loop starts at j=0, so each (i,j) pair is swapped twice
// (once when visiting (i,j), once when visiting (j,i)), leaving the matrix unchanged.
void transpose(int m[4][4]) {
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) {      // BUG: should be j = i + 1
            int t = m[i][j];
            m[i][j] = m[j][i];
            m[j][i] = t;
        }
    }
}

int main() {
    int m[4][4] = {
        { 1,  2,  3,  4},
        { 5,  6,  7,  8},
        { 9, 10, 11, 12},
        {13, 14, 15, 16}
    };
    transpose(m);
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) printf("%d ", m[i][j]);
        printf("\n");
    }
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>

void transpose(int m[4][4]) {
    for (int i = 0; i < 4; i++) {
        for (int j = i + 1; j < 4; j++) {  // FIX: upper triangle only
            int t = m[i][j];
            m[i][j] = m[j][i];
            m[j][i] = t;
        }
    }
}

int main() {
    int m[4][4] = {
        { 1,  2,  3,  4},
        { 5,  6,  7,  8},
        { 9, 10, 11, 12},
        {13, 14, 15, 16}
    };
    transpose(m);
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) printf("%d ", m[i][j]);
        printf("\n");
    }
    return 0;
}
""",
        "expected_output": "1 5 9 13 \n2 6 10 14 \n3 7 11 15 \n4 8 12 16 \n",
    },

    # ── 10. Fast exponentiation: missing odd-exponent multiplication ──────────
    {
        "id": "010_fast_power",
        "description": "Fast exponentiation silently drops factors when the exponent is odd",
        "bug_type": "logic-error",
        "buggy_code": r"""
#include <cstdio>

// Compute a^b via squaring.
// BUG: for odd b we square (a^(b/2)) but forget to multiply by a one extra time.
long long power(long long a, int b) {
    if (b == 0) return 1;
    long long half = power(a, b / 2);
    return half * half;                  // BUG: missing `* a` when b is odd
}

int main() {
    printf("%lld\n", power(2, 10));      // 1024
    printf("%lld\n", power(3, 5));       // 243
    printf("%lld\n", power(2, 0));       // 1
    printf("%lld\n", power(5, 3));       // 125
    return 0;
}
""",
        "fixed_code": r"""
#include <cstdio>

long long power(long long a, int b) {
    if (b == 0) return 1;
    long long half = power(a, b / 2);
    long long sq = half * half;
    return (b % 2 == 0) ? sq : sq * a;   // FIX: handle odd exponent
}

int main() {
    printf("%lld\n", power(2, 10));
    printf("%lld\n", power(3, 5));
    printf("%lld\n", power(2, 0));
    printf("%lld\n", power(5, 3));
    return 0;
}
""",
        "expected_output": "1024\n243\n1\n125\n",
    },
]
