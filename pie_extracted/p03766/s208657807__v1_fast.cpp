#include<bits/stdc++.h>

#define ll long long

using namespace std;

const int maxn=1000005;

const ll mod=1e9+7;

ll m,ans=0,f[maxn],s[maxn];

int n;

int main(){

	scanf("%d",&n);

	m=1ll*(n-1)*(n-1)%mod;

	ans=m+1+(n>2);

	f[0]=s[0]=1;

	for(int i=1;i<n;i++){

		f[i]=f[i-1]+(i>2?s[i-3]:0);

		s[i]=s[i-1]+f[i];

		f[i]%=mod;

		s[i]%=mod;

		if(i!=n-1)ans=(ans+1ll*f[i]*(m+min(n-1,i+2))%mod)%mod;

		else ans=(ans+1ll*f[i]*n%mod)%mod;

	}

	printf("%lld\n",ans);

	return 0;

}