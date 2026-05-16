#include <string>

#include <cstdio>

#include <map>

#include <vector>

#include <algorithm>

using namespace std;

map<string, vector<pair<string,int> > >m; //no direction graph



char b1[99],b2[99];

void main2(int n){

	m.clear();

	string s1,s2;

	for(;n;n--){

		int d;

		scanf(" 1 %s = 10^%d %s",b1,&d,b2);

		s1=b1,s2=b2;

		m[s1].push_back(make_pair(s2,d));

		m[s2].push_back(make_pair(s1,-d));

	}

	for(;!m.empty();){

		string s=m.begin()->first;

		vector<pair<string,int> >st={{s,0}};

		map<string,int>memo={{s,0}};

		for(;!st.empty();){

			auto p=*st.rbegin();st.pop_back();

			string cur=p.first;int d=p.second;

			memo[cur]=d;

			for(auto &e:m[cur]){

				if(memo.find(e.first)==memo.end()){

					st.emplace_back(e.first,d+e.second);

				}else if(memo[e.first]!=d+e.second){

					puts("No");

					return;

				}

			}

		}

		for(auto &e:memo)m.erase(m.find(e.first));

	}

	puts("Yes");

}

int main(){int n;for(;~scanf("%d",&n)&&n;)main2(n);}