#include<iostream>

#include<cstdio>

#include<map>

#include<algorithm>

using namespace std;

const int MAXN = 100010;

long long sum[MAXN];

int a[MAXN],aa[MAXN],b[MAXN],c[MAXN];

int n;

int lowbit(int x){return x&(-x);}

void update(int x,int n){

	for (int i=x;i<=n;i+=lowbit(i)) {

		sum[i]++;

	}

}

int getSum(int x) {

	int ans = 0;

	for (int i=x;i>0;i-=lowbit(i)) {

		ans += sum[i];

	}

	return ans;

}

long long check(int x) {

	b[0] = 0;c[0] = 0;

	for (int i=1;i<=n;i++) {

		if (a[i]<=x) b[i] = 1;

		else b[i] = -1;

	}

	for (int i=1;i<=n;i++) {

		b[i] = b[i-1] + b[i];

		c[i] = b[i];

	}

	sort(c,c+1+n);

	int cnt = 1;

	map<int,int> mp;

	mp[c[0]] = 1;

	for (int i=1;i<=n;i++) {

		if (c[i]!=c[i-1]) {

			cnt++;

			mp[c[i]] = cnt;

		}

	}

	for (int i=0;i<=cnt;i++) sum[i]=0;

	long long res = 0;

	update(mp[0],cnt);

	for (int i=1;i<=n;i++) {

		res += getSum(mp[b[i]]-1);

		update(mp[b[i]],cnt);

	}

	return res;

}

int main()

{

	scanf("%d",&n);

	for (int i=1;i<=n;i++) scanf("%d",&a[i]);

	for (int i=1;i<=n;i++) aa[i] = a[i];

	sort(aa+1,aa+1+n);

	long long k = 1LL * n*(n+1)/2/2+1;

	int l = 1,r = n,mid,ans;

	while(l<=r) {

		mid = (l+r) / 2;

		if (check(aa[mid])>=k) {

			ans = aa[mid];

			r = mid - 1;

		}

		else l = mid + 1;

	}

	printf("%d\n",ans);

}