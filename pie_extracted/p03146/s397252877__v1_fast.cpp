#include <bits/stdc++.h>



using namespace std;



#define USE_CPPIO() ios_base::sync_with_stdio(0); cin.tie(0)



int main(int argc, char const *argv[]){



	map<int, int> m;

	int input, ans, sta;

	while(cin >> input){

		sta = 0;

		ans = 1;

		m[input] = 1;

		while(1){

			if (input % 2 == 0){

				ans++;

				input /= 2;

				m[input] += 1;

			}

			else{

				ans++;

				input = (3*input + 1);

				m[input] +=1;

			}

			for (map<int,int>::iterator it=m.begin(); it != m.end(); ++it){

				if (it->second == 2){

					cout << ans << endl;

					sta = 1;

					break;

				}

			}

			if(sta == 1)	break;

		}

	}



	return 0;

}