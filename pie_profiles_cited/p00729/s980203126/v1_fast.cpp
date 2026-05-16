// ACM-ICPCà\I2007 B. OC/OAEgL^ÌðÍ



#include <iostream>

#include <vector>



using namespace std;



int main(){

	int n, m;

	while(cin >> n >> m, n){

		cin >> n;

		vector <int> count(m, 0);

		vector < vector< pair<int,int> > > rec(m);

		int t, p, s;

		for(int i=0;i<n;i++){

			cin >> t >> p >> p >> s;

			p--;

			if(s == 1){

				if(count[p] == 0)

					rec[p].push_back(make_pair(t,t));

				count[p]++;

			} else {

				count[p]--;

				if(count[p] == 0)

					rec[p].back().second = t;

			}

		}

		cin >> n;

		for(int i=0;i<n;i++){

			int ans = 0;

			cin >> s >> t >> p;

			p--;

			for(int j=0;j<rec[p].size();j++){

				ans += max(0, min(t, rec[p][j].second) - max(s, rec[p][j].first));

			}

			cout << ans << endl;

		}

	}

}