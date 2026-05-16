#include<cstdio>

#include<cstring>

#include<cmath>

#include<cstdlib>

#include<map>

#include<queue>

#include<iostream>

#include<algorithm>

#define m(a,b) memset(a,b,sizeof(a));

using namespace std;

const int inf = 1 << 30;

const int maxn = 1e5;

typedef long long LL;

int main(){

	int a,b,c;

	cin >> a >> b >> c;

	bool ans = false;

	for(int i = 1;i<b;i++){

		if((a*i)%b == c%b)

			ans = true;

	}

	if(ans)

		cout << "YES" << endl;

	else

		cout << "NO" << endl;

	return 0;

}