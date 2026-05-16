/*

 * VJUDGE B - Collatz Problem

 * author: roy4801

 * (C++)

 */

#include <bits/stdc++.h>



using namespace std;



#define PROB "B"

#define TESTC ""



#define USE_CPPIO() ios_base::sync_with_stdio(0); cin.tie(0)

typedef long long int LL;

typedef unsigned long long ULL;

typedef pair<int, int> P;

#define F first

#define S second

#define INF 0x3f3f3f3f

#define MP make_pair

#define MT make_tuple

#define PB push_back

#define N 1000000

bool arr[N+5];

int n, cnt; // s, times

int main()

{

	#ifdef DBG

	freopen("./testdata/" PROB TESTC ".in", "r", stdin);

	freopen("./testdata/" PROB ".out", "w", stdout);

	#endif

	while(cin >> n)

	{

		memset(arr, 0, sizeof(arr));

		cnt = 1;

		//

		while(true)

		{

			arr[n] = true;

			if(n & 1) // odd

			{

				n *= 3;

				n += 1;

			}

			else

			{

				n /= 2;

			}



			cnt++;

			if(arr[n])

				break;

		}



		printf("%d\n", cnt);

	}



	return 0;

}
