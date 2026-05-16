#include <bits/stdc++.h>

#define LL long long



using namespace std;

const int maxn = 1e5+100;

LL ans,a[maxn],cnt[maxn];



int main(){

    ios::sync_with_stdio(false);

    cin.tie(0);

    cout.tie(0);



    int i,n,t;

    cin >> n;

    for (int i = 1;i<=n;i++){

        cin >> a[i];

        ans +=a[i];

        cnt[a[i]]++;

    }

    cin >> t;



    while(t--){

        int x,y;

        cin >> x >> y;

        ans -= cnt[x] * x;

        ans+= cnt[x] * y;

        cnt[y]+=cnt[x], cnt[x]=0;

        cout << ans << endl;

    }



    return 0;

}