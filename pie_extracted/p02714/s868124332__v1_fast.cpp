#include <bits/stdc++.h>

typedef long long ll;

using namespace std;

#define repr(i,a,b) for(int i=a;i<b;i++)

#define rep(i,n) for(int i=0;i<n;i++)

#define invrepr(i,a,b) for(int i=b-1;i>=a;i--)

#define invrep(i,n) invrepr(i,0,n)

#define repitr(itr,a) for(auto itr=a.begin();itr!=a.end();++itr)

const int MOD=1e9+7;

 



int main() {

    ios_base::sync_with_stdio(false);

    

    int n;

    string s; 

    cin >> n;

    cin >> s;

    vector<int> r,g,b;

    rep(i,n) {

        if (s[i]=='R') r.push_back(i);

        else if (s[i]=='G') g.push_back(i);

        else b.push_back(i);

    }

    ll ans=r.size()*g.size()*b.size();

    rep(i,n) {

        repr(j,i+1,n-1) {

            int k=j+(j-i);

            if (k>=n) continue;

            if (s[i]!=s[j] && s[j]!=s[k] && s[k]!=s[i]) --ans;

        }

    }

    cout << ans << endl;

    

}