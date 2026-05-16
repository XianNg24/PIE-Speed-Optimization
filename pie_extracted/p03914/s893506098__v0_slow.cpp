#include <bits/stdc++.h>

#include <ext/pb_ds/assoc_container.hpp>

#include <ext/pb_ds/tree_policy.hpp>



using namespace std;

using namespace __gnu_pbds;



#define fi first

#define se second

#define mp make_pair

#define pb push_back

#define fbo find_by_order

#define ook order_of_key



typedef long long ll;

typedef pair<ll,ll> ii;

typedef vector<int> vi;

typedef long double ld; 

typedef tree<int, null_type, less<int>, rb_tree_tag, tree_order_statistics_node_update> pbds;

typedef set<int>::iterator sit;

typedef map<int,int>::iterator mit;

typedef vector<int>::iterator vit;



const int MOD = 1e9 + 7;

int dp[301][301][301];



void add(int &a, int b)

{

	a+=b;

	while(a>=MOD) a-=MOD;

}



int mult(int a, int b)

{

	return (a*1LL*b)%MOD;

}



int main()

{

	ios_base::sync_with_stdio(0); cin.tie(0);

	int n, m; cin>>n>>m;

	dp[0][1][0]=1;

	for(int i=0;i<m;i++)

	{

		for(int j=0;j<=n;j++)

		{

			for(int k=0;j+k<=n;k++)

			{

				int v=dp[i][j][k];

				if(v!=0)

				{

					add(dp[i+1][j+k][0],mult(j,v));

					add(dp[i+1][j][k],mult(k,v));

					if(n-j-k>0) add(dp[i+1][j][k+1],mult(n-j-k,v));

				}

			}

		}

	}

	cout<<dp[m][n][0]<<'\n';

}
