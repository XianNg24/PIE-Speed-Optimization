#include <iostream>

#include<cmath>

using namespace std;



int main()

{

    int x,y,A,B;

    cin>>A>>B;

    x=max(A+B,A-B);

    y=max(x,A*B);

    cout<<y;

    return 0;

}
