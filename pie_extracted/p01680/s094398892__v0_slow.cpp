#include <iostream>

#include <cstdio>

#include <cstring>

#include <cstdlib>

#include <cmath>

#include <algorithm>

#include <queue>

#include <map>

#include <set>

#include <vector>

#include <string>

#include <stack>

#include <bitset>

#define maxn 100009

using namespace std;

const int MOD=1e9+7;

int p[maxn];

long long bin[maxn];

int findset(int x)

{

	return x==p[x]?x:p[x]=findset(p[x]);

}

void unionset(int x,int y)

{

	 p[findset(x)]=findset(y);

}

int main()

{

	int n,m,x,y;

	bin[0]=1;

	for(int i=1;i<maxn;i++)

		bin[i]=2*bin[i-1]%MOD;

	while(scanf("%d%d",&n,&m)!=EOF&&n+m)

	{

		for(int i=0;i<=n;i++)

			p[i]=i;

		for(int i=0;i<m;i++)

		{

			scanf("%d%d",&x,&y);

			unionset(x,y);

		}

		int cnt=0;

		for(int i=1;i<=n;i++)

		{

			if(p[i]==i)

			{

				cnt++;

			}

		}

		int ans=bin[cnt];

		if(cnt!=n)

			ans=(ans+1)%MOD;

		printf("%d\n",ans);

	}

	return 0;

}