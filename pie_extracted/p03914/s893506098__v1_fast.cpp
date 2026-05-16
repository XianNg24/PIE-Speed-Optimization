#include <bits/stdc++.h>

using namespace std;

const int N = 305;

const int MOD = 1e9 + 7;

int dp[N][N][N];

int n, m;

int main() {

    scanf("%d%d", &n, &m);

    dp[0][1][0] = 1;

    for (int i = 0; i < m; i++) {

        for (int j = 1; j <= min(n, m); j++) {

            for (int k = 0; j + k <= min(n, m); k++) {

                if (!dp[i][j][k]) continue;

                dp[i + 1][j + k][0] =

                    (dp[i + 1][j + k][0] + 1LL * dp[i][j][k] * j) % MOD;

                dp[i + 1][j][k + 1] =

                    (dp[i + 1][j][k + 1] + 1LL * dp[i][j][k] * (n - j - k)) %

                    MOD;

                dp[i + 1][j][k] =

                    (dp[i + 1][j][k] + 1LL * dp[i][j][k] * k) % MOD;

                //printf("(%d,%d,%d):[%d]\n", i, j, k, dp[i][j][k]);

            }

        }

    }

    printf("%d\n", dp[m][n][0]);

    return 0;

}