#include <bits/stdc++.h>



using namespace std;



const int N = 307;



double f[N + 10][N + 10][N + 10];



int main() {

    int n;

    cin >> n;

    int c1 = 0, c2 = 0, c3 = 0;

    for (int i = 1; i <= n; i++) {

        int x;

        cin >> x;

        if (x == 1) {

            c1++;

        } else if (x == 2) {

            c2++;

        } else {

            c3++;

        }

    }



    for (int k = 0; k < N; k++) {

        for (int j = 0; j + k < N; j++) {

            for (int i = 0; i + j + k < N; i++) {

                if (i == 0 && j == 0 && k == 0) {

                    continue;

                }

                if (i + j + k > N) {

                    continue;

                }

                double wait = 1.0 * n / (i + j + k);

                double pi = 1.0 * i / (i + j + k);

                double pj = 1.0 * j / (i + j + k);

                double pk = 1.0 * k / (i + j + k);



                if (i) {

                    f[i][j][k] += pi * f[i - 1][j][k];

                }

                if (j) {

                    f[i][j][k] += pj * f[i + 1][j - 1][k];

                }

                if (k) {

                    f[i][j][k] += pk * f[i][j + 1][k - 1];

                }

                f[i][j][k] += wait;

            }

        }

    }

    printf ("%.9lf", f[c1][c2][c3]);

    return 0;

}


