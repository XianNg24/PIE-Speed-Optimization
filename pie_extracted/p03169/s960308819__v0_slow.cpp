#include<iostream>

#include<cstdio>

using namespace std;

const int Maxn=300+5;

int n,x,cnt[4];

double dp[Maxn][Maxn][Maxn];

bool vis[Maxn][Maxn][Maxn];

double w(int i,int j,int k)

{	if(!i&&!j&&!k)return 0;

	if(vis[i][j][k])return dp[i][j][k];

	vis[i][j][k]=1;

	if(i)dp[i][j][k]+=w(i-1,j,k)*i/n;

	if(j)dp[i][j][k]+=w(i+1,j-1,k)*j/n;

	if(k)dp[i][j][k]+=w(i,j+1,k-1)*k/n;

	dp[i][j][k]++;

	dp[i][j][k]/=1.0*(i+j+k)/n;

	return dp[i][j][k];

}

int main()

{	scanf("%d",&n);

	for(int i=1;i<=n;i++)

	{	scanf("%d",&x);

		cnt[x]++;

	}

	printf("%.10lf",w(cnt[1],cnt[2],cnt[3]));

	return 0;

}