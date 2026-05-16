#include<bits/stdc++.h>

#define rush() int T;scanf("%d",&T);int kase=1;while(T--)

#define pb(x) push_back(x)

#define pr pair<int,int>

#define mem(a) memset(a,0,sizeof(a))

#define  fi first

#define  se second

using namespace std;

typedef long long ll;

const ll maxn=2e6+5;

const ll mod=1e9+7;

ll quickpow(ll x,ll y,ll mod){ll ans=1;while(y){if(y&1)ans=ans*x%mod;x=x*x%mod;y>>=1;}return ans;}



int a[maxn]={0};



int main()

{

    int n;

    cin>>n;

    ll sum=0;

    for(int i=0;i<n;i++)

    {

        int x;

        cin>>x;

        sum+=x;

        a[x]++;

    }

    int q;

    cin>>q;

    while(q--)

    {

        int b,c;

        cin>>b>>c;

        sum+=(c-b)*a[b];

        a[c]+=a[b];

        a[b]=0;

        cout<<sum<<endl;

    }

    return 0;

}
