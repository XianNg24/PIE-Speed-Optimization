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

    vector<vector<int>> r(3);

    ll ans=0;

    rep(i,n) {

        if (s[i]=='R') r[0].push_back(i);

        else if (s[i]=='G') r[1].push_back(i);

        else r[2].push_back(i);

    }

    string t="RGB";

    vector<int> a= {0,1,2};



    sort(a.begin(), a.end());

    do

    {

        rep(i,n-2) {

            if (s[i]==t[a[0]]) {

                repr(j,i+1,n-1) {

                    if (s[j]==t[a[1]]) {

                        ans+=r[a[2]].end()-lower_bound(r[a[2]].begin(),r[a[2]].end(),j);

                        int k=lower_bound(r[a[2]].begin(),r[a[2]].end(),j+(j-i))-r[a[2]].begin();

                        if (k>=r[a[2]].size()) continue;

                        if (r[a[2]][k]==j+(j-i)) --ans;

                    }

                }

            }

        }

    } while (next_permutation(a.begin(), a.end()));

    cout << ans << endl;

    

}